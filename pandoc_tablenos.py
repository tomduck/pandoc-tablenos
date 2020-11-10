#! /usr/bin/env python

"""pandoc-tablenos: a pandoc filter that inserts table nos. and refs."""


__version__ = '2.3.0'


# Copyright 2015-2020 Thomas J. Duck.
# All rights reserved.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


# OVERVIEW
#
# The basic idea is to scan the document twice in order to:
#
#   1. Insert text for the table number in each table caption.
#      For LaTeX, insert \label{...} instead.  The table labels
#      and associated table numbers are stored in the global
#      targets tracker.
#
#   2. Replace each reference with a table number.  For LaTeX,
#      replace with \ref{...} instead.
#
# This is followed by injecting header code as needed for certain output
# formats.


# pylint: disable=invalid-name

import re
import functools
import argparse
import json
import copy
import textwrap
import uuid

from pandocfilters import walk
from pandocfilters import Table, Str, Space, RawBlock, RawInline, Math, Span

import pandocxnos
from pandocxnos import PandocAttributes
from pandocxnos import STRTYPES, STDIN, STDOUT, STDERR
from pandocxnos import NBSP
from pandocxnos import elt, check_bool, get_meta, extract_attrs
from pandocxnos import repair_refs, process_refs_factory, replace_refs_factory
from pandocxnos import insert_secnos_factory, delete_secnos_factory
from pandocxnos import attach_attrs_factory, detach_attrs_factory
from pandocxnos import version


# Patterns for matching labels and references
LABEL_PATTERN = re.compile(r'(tbl:[\w/-]*)')

# Meta variables; may be reset elsewhere
captionname = 'Table'   # The caption name
separator = 'colon'     # The caption separator
cleveref = False        # Flags that clever references should be used
capitalise = False      # Default setting for capitalizing plusname
plusname = ['table', 'tables']  # Sets names for mid-sentence references
starname = ['Table', 'Tables']  # Sets names for references at sentence start
numbersections = False  # Flags that tables should be numbered by section
secoffset = 0           # Section number offset
warninglevel = 2        # 0 - no warnings; 1 - some warnings; 2 - all warnings

# Processing state variables
cursec = None  # Current section
Ntargets = 0   # Number of targets in current section (or document)
targets = {}   # Global targets tracker

# Processing flags
captionname_changed = False     # Flags the caption name changed
separator_changed = False       # Flags the caption separator changed
plusname_changed = False        # Flags that the plus name changed
starname_changed = False        # Flags that the star name changed
has_unnumbered_tables = False   # Flags unnumbered tables were found
has_tagged_tables = False       # Flags a tagged table was found

PANDOCVERSION = None
AttrTable = None


# Actions --------------------------------------------------------------------

# pylint: disable=unused-argument
def attach_attrs_table(key, value, fmt, meta):
    """Extracts attributes and attaches them to element."""

    # We can't use attach_attrs_factory() because Table is a block-level element

    # Tables are attributed as of pandoc 2.10.  There is no native mechanism
    # (yet) to populate those attributes.  This is coming.  See the
    # Revision history for pandoc 2.10.1 at https://pandoc.org/releases.html.

    if key in ['Table']:
        if version(PANDOCVERSION) < version('2.10'):
            assert len(value) == 5
            caption = value[0]  # caption, align, x, head, body
        elif version(PANDOCVERSION) < version('2.11'):
            assert len(value) == 6
            assert value[1]['t'] == 'Caption'
            if value[1]['c'][1]:
                assert value[1]['c'][1][0]['t'] == 'Plain'
                caption = value[1]['c'][1][0]['c']
            else:
                return  # There is no caption
        else:
            assert len(value) == 6
            assert value[1][0] is None
            if value[1][1]:
                assert value[1][1][0]['t'] == 'Plain'
                caption = value[1][1][0]['c']
            else:
                return  # There is no caption

        # Set n to the index where the attributes start
        n = 0
        while n < len(caption) and not \
          (caption[n]['t'] == 'Str' and caption[n]['c'].startswith('{')):
            n += 1

        try:
            # Read the attributes from the caption
            attrs = extract_attrs(caption, n)
            if version(PANDOCVERSION) < version('2.10'):
                # Insert the attributes
                value.insert(0, attrs.list)
            else:
                # Overwrite the attributes
                value[0] = attrs.list
        except (ValueError, IndexError):
            pass

# pylint: disable=too-many-branches
def _process_table(value, fmt):
    """Processes the table.  Returns a dict containing table properties."""

    # pylint: disable=global-statement
    global cursec    # Current section being processed
    global Ntargets  # Number of refs in current section (or document)
    global has_unnumbered_tables  # Flags unnumbered tables were found

    # Initialize the return value
    table = {'is_unnumbered': False,
             'is_unreferenceable': False,
             'is_tagged': False}

    # Bail out if there are no attributes
    if len(value) == 5:
        has_unnumbered_tables = True
        table.update({'is_unnumbered': True, 'is_unreferenceable': True})
        return table

    # Parse the table
    attrs = table['attrs'] = PandocAttributes(value[0], 'pandoc')
    if version(PANDOCVERSION) < version('2.10'):
        table['caption'] = value[1]
    elif version(PANDOCVERSION) < version('2.11'):
        if value[1]['c'][1]:
            table['caption'] = value[1]['c'][1][0]['c']
        else:
            table['caption'] = []
    else:
        if value[1][1]:
            table['caption'] = value[1][1][0]['c']
        else:
            table['caption'] = []

    # Bail out if the label does not conform to expectations
    if not LABEL_PATTERN.match(attrs.id):
        has_unnumbered_tables = True
        table.update({'is_unnumbered':True, 'is_unreferenceable':True})
        return table

    # Identify unreferenceable tables
    if attrs.id == 'tbl:': # Make up a unique description
        attrs.id = 'tbl:' + str(uuid.uuid4())
        table['is_unreferenceable'] = True

    # Update the current section number
    if attrs['secno'] != cursec:  # The section number changed
        cursec = attrs['secno']   # Update the global section tracker
        if numbersections:
            Ntargets = 0          # Resets the global target counter

    # Increment the targets counter
    if 'tag' not in attrs:
        Ntargets += 1

    # Pandoc's --number-sections supports section numbering latex/pdf, html,
    # epub, and docx
    if numbersections:
        if fmt in ['html', 'html4', 'html5', 'epub', 'epub2', 'epub3',
                   'docx'] and \
          'tag' not in attrs:
            attrs['tag'] = str(cursec+secoffset) + '.' + str(Ntargets)

    # Save reference information
    table['is_tagged'] = 'tag' in attrs
    if table['is_tagged']:
        # Remove any surrounding quotes
        if attrs['tag'][0] == '"' and attrs['tag'][-1] == '"':
            attrs['tag'] = attrs['tag'].strip('"')
        elif attrs['tag'][0] == "'" and attrs['tag'][-1] == "'":
            attrs['tag'] = attrs['tag'].strip("'")
        targets[attrs.id] = pandocxnos.Target(attrs['tag'], cursec,
                                              attrs.id in targets)
    else:  # ... then save the table number
        targets[attrs.id] = pandocxnos.Target(Ntargets, cursec,
                                              attrs.id in targets)

    return table


# pylint: disable=too-many-statements
def _adjust_caption(fmt, table, value):
    """Adjusts the caption."""
    attrs, caption = table['attrs'], table['caption']
    num = targets[attrs.id].num
    if fmt in['latex', 'beamer']:  # Append a \label if this is referenceable
        if not table['is_unreferenceable']:
            tmp = [RawInline('tex', r'\label{%s}'%attrs.id)]
            if version(PANDOCVERSION) < version('2.10'):
                value[1] += tmp
            elif version(PANDOCVERSION) < version('2.11'):
                value[1]['c'][1][0]['c'] += tmp
            else:
                value[1][1][0]['c'] += tmp

    else:  # Hard-code in the caption name and number/tag
        sep = {'none':'', 'colon':':', 'period':'.', 'space':' ',
               'quad':u'\u2000', 'newline':'\n'}[separator]

        if isinstance(num, int):  # Numbered reference
            if fmt in ['html', 'html4', 'html5', 'epub', 'epub2', 'epub3']:
                tmp = [RawInline('html', r'<span>'),
                       Str(captionname+NBSP), Str('%d%s'%(num, sep)),
                       RawInline('html', r'</span>')]
                if version(PANDOCVERSION) < version('2.10'):
                    value[1] = tmp
                elif version(PANDOCVERSION) < version('2.11'):
                    value[1]['c'][1][0]['c'] = tmp
                else:
                    value[1][1][0]['c'] = tmp
            else:
                tmp = [Str(captionname+NBSP), Str('%d%s'%(num, sep))]
                if version(PANDOCVERSION) < version('2.10'):
                    value[1] = tmp
                elif version(PANDOCVERSION) < version('2.11'):
                    value[1]['c'][1][0]['c'] = tmp
                else:
                    value[1][1][0]['c'] = tmp
        else:  # Tagged reference
            assert isinstance(num, STRTYPES)
            if num.startswith('$') and num.endswith('$'):
                math = num.replace(' ', r'\ ')[1:-1]
                els = [Math({"t":"InlineMath", "c":[]}, math), Str(sep)]
            else:  # Text
                els = [Str(num + sep)]
            if fmt in ['html', 'html4', 'html5', 'epub', 'epub2', 'epub3']:
                tmp = [RawInline('html', r'<span>'),
                       Str(captionname+NBSP)] + \
                      els + [RawInline('html', r'</span>')]
                if version(PANDOCVERSION) < version('2.10'):
                    value[1] = tmp
                elif version(PANDOCVERSION) < version('2.11'):
                    value[1]['c'][1][0]['c'] = tmp
                else:
                    value[1][1][0]['c'] = tmp
            else:
                tmp = [Str(captionname+NBSP)] + els
                if version(PANDOCVERSION) < version('2.10'):
                    value[1] = tmp
                elif version(PANDOCVERSION) < version('2.11'):
                    value[1]['c'][1][0]['c'] = tmp
                else:
                    value[1][1][0]['c'] = tmp

        tmp = [Space()] + list(caption)
        if version(PANDOCVERSION) < version('2.10'):
            value[1] += tmp
        elif version(PANDOCVERSION) < version('2.11'):
            value[1]['c'][1][0]['c'] += tmp
        else:
            value[1][1][0]['c'] += tmp

def _add_markup(fmt, table, value):
    """Adds markup to the output."""

    # pylint: disable=global-statement
    global has_tagged_tables  # Flags a tagged tables was found

    if table['is_unnumbered']:
        if fmt in ['latex', 'beamer']:
            # Use the no-prefix-table-caption environment
            return [RawBlock('tex',
                             r'\begin{tablenos:no-prefix-table-caption}'),
                    Table(*(value if len(value) == 5 or \
                            version(PANDOCVERSION) >= version('2.10') \
                            else value[1:])),
                    RawBlock('tex', r'\end{tablenos:no-prefix-table-caption}')]
        return None  # Nothing to do

    attrs = table['attrs']
    ret = None

    if fmt in ['latex', 'beamer']:
        if table['is_tagged']:  # A table cannot be tagged if it is unnumbered
            has_tagged_tables = True
            ret = [RawBlock('tex', r'\begin{tablenos:tagged-table}[%s]' % \
                            targets[attrs.id].num),
                   AttrTable(*value),
                   RawBlock('tex', r'\end{tablenos:tagged-table}')]
    elif fmt in ('html', 'html4', 'html5', 'epub', 'epub2', 'epub3'):
        if LABEL_PATTERN.match(attrs.id):
            # Enclose table in hidden div
            pre = RawBlock('html', '<div id="%s" class="tablenos">'%attrs.id)
            post = RawBlock('html', '</div>')
            ret = [pre, AttrTable(*value), post]
    elif fmt == 'docx':
        # As per http://officeopenxml.com/WPhyperlink.php
        bookmarkstart = \
          RawBlock('openxml',
                   '<w:bookmarkStart w:id="0" w:name="%s"/>'
                   %attrs.id)
        bookmarkend = \
          RawBlock('openxml', '<w:bookmarkEnd w:id="0"/>')
        ret = [bookmarkstart, AttrTable(*value), bookmarkend]
    return ret


# pylint: disable=unused-argument, too-many-return-statements
def process_tables(key, value, fmt, meta):
    """Processes the attributed tables."""

    # Process block-level Table elements
    if key == 'Table':

        # Process the table
        table = _process_table(value, fmt)
        if 'attrs' in table and table['attrs'].id:
            _adjust_caption(fmt, table, value)
        return _add_markup(fmt, table, value)

    return None


# TeX blocks -----------------------------------------------------------------

# Define an environment that disables table caption prefixes.  Counters
# must be saved and later restored.  The \thetable and \theHtable counter
# must be set to something unique so that duplicate internal names are avoided
# (see Sect. 3.2 of
# http://ctan.mirror.rafal.ca/macros/latex/contrib/hyperref/doc/manual.html).
NO_PREFIX_CAPTION_ENV_TEX = r"""
%% pandoc-tablenos: environment to disable table caption prefixes
\makeatletter
\newcounter{tableno}
\newenvironment{tablenos:no-prefix-table-caption}{
  \caption@ifcompatibility{}{
    \let\oldthetable\thetable
    \let\oldtheHtable\theHtable
    \renewcommand{\thetable}{tableno:\thetableno}
    \renewcommand{\theHtable}{tableno:\thetableno}
    \stepcounter{tableno}
    \captionsetup{labelformat=empty}
  }
}{
  \caption@ifcompatibility{}{
    \captionsetup{labelformat=default}
    \let\thetable\oldthetable
    \let\theHtable\oldtheHtable
    \addtocounter{table}{-1}
  }
}
\makeatother
"""

# Define an environment for tagged tables
TAGGED_TABLE_ENV_TEX = r"""
%% pandoc-tablenos: environment for tagged tables
\newenvironment{tablenos:tagged-table}[1][]{
  \let\oldthetable\thetable
  \let\oldtheHtable\theHtable
  \renewcommand{\thetable}{#1}
  \renewcommand{\theHtable}{#1}
}{
  \let\thetable\oldthetable
  \let\theHtable\oldtheHtable
  \addtocounter{table}{-1}
}
"""

# Reset the caption name; i.e. change "Table" at the beginning of a caption
# to something else.
CAPTION_NAME_TEX = r"""
%% pandoc-tablenos: change the caption name
\renewcommand{\tablename}{%s}
"""

# Reset the label separator; i.e. change the colon after "Table 1:" to
# something else.
CAPTION_SEPARATOR_TEX = r"""
%% pandoc-tablenos: change the caption separator
\captionsetup[table]{labelsep=%s}
"""

# Define some tex to number tables by section
NUMBER_BY_SECTION_TEX = r"""
%% pandoc-tablenos: number tables by section
\numberwithin{table}{section}
"""

# Section number offset
SECOFFSET_TEX = r"""
%% pandoc-fignos: section number offset
\setcounter{section}{%s}
"""


# Main program ---------------------------------------------------------------

# pylint: disable=too-many-branches,too-many-statements
def process(meta):
    """Saves metadata fields in global variables and returns a few
    computed fields."""

    # pylint: disable=global-statement
    global captionname     # The caption name
    global separator       # The caption separator
    global cleveref        # Flags that clever references should be used
    global capitalise      # Flags that plusname should be capitalised
    global plusname        # Sets names for mid-sentence references
    global starname        # Sets names for references at sentence start
    global numbersections  # Flags that sections should be numbered by section
    global secoffset       # Section number offset
    global warninglevel    # 0 - no warnings; 1 - some; 2 - all
    global captionname_changed  # Flags the caption name changed
    global separator_changed    # Flags the caption separator changed
    global plusname_changed     # Flags that the plus name changed
    global starname_changed     # Flags that the star name changed

    # Read in the metadata fields and do some checking

    for name in ['tablenos-warning-level', 'xnos-warning-level']:
        if name in meta:
            warninglevel = int(get_meta(meta, name))
            pandocxnos.set_warning_level(warninglevel)
            break

    metanames = ['tablenos-warning-level', 'xnos-warning-level',
                 'tablenos-caption-name',
                 'tablenos-caption-separator', 'xnos-caption-separator',
                 'tablenos-cleveref', 'xnos-cleveref',
                 'xnos-capitalise', 'xnos-capitalize',
                 'tablenos-plus-name', 'tablenos-star-name',
                 'tablenos-number-by-section', 'xnos-number-by-section',
                 'xnos-number-offset']

    if warninglevel:
        for name in meta:
            if (name.startswith('tablenos') or name.startswith('xnos')) and \
              name not in metanames:
                msg = textwrap.dedent("""
                          pandoc-tablenos: unknown meta variable "%s"
                      """ % name)
                STDERR.write(msg)

    if 'tablenos-caption-name' in meta:
        old_captionname = captionname
        captionname = get_meta(meta, 'tablenos-caption-name')
        captionname_changed = captionname != old_captionname
        assert isinstance(captionname, STRTYPES)

    for name in ['tablenos-caption-separator', 'xnos-caption-separator']:
        if name in meta:
            old_separator = separator
            separator = get_meta(meta, name)
            if separator not in \
              ['none', 'colon', 'period', 'space', 'quad', 'newline']:
                msg = textwrap.dedent("""
                          pandoc-tablenos: caption separator must be one of
                          none, colon, period, space, quad, or newline.
                      """ % name)
                STDERR.write(msg)
                continue
            separator_changed = separator != old_separator
            break

    for name in ['tablenos-cleveref', 'xnos-cleveref']:
        # 'xnos-cleveref' enables cleveref in all 3 of fignos/eqnos/tablenos
        if name in meta:
            cleveref = check_bool(get_meta(meta, name))
            break

    for name in ['xnos-capitalize', 'xnos-capitalise']:
        # 'xnos-capitalise' enables capitalise in all 3 of
        # fignos/eqnos/tablenos.  Since this uses an option in the caption
        # package, it is not possible to select between the three (use
        # 'tablenos-plus-name' instead.  'xnos-capitalize' is an alternative
        # spelling
        if name in meta:
            capitalise = check_bool(get_meta(meta, name))
            break

    if 'tablenos-plus-name' in meta:
        tmp = get_meta(meta, 'tablenos-plus-name')
        old_plusname = copy.deepcopy(plusname)
        if isinstance(tmp, list):  # The singular and plural forms were given
            plusname = tmp
        else:  # Only the singular form was given
            plusname[0] = tmp
        plusname_changed = plusname != old_plusname
        assert len(plusname) == 2
        for name in plusname:
            assert isinstance(name, STRTYPES)
        if plusname_changed:
            starname = [name.title() for name in plusname]

    if 'tablenos-star-name' in meta:
        tmp = get_meta(meta, 'tablenos-star-name')
        old_starname = copy.deepcopy(starname)
        if isinstance(tmp, list):
            starname = tmp
        else:
            starname[0] = tmp
        starname_changed = starname != old_starname
        assert len(starname) == 2
        for name in starname:
            assert isinstance(name, STRTYPES)

    for name in ['tablenos-number-by-section', 'xnos-number-by-section']:
        if name in meta:
            numbersections = check_bool(get_meta(meta, name))
            break

    if 'xnos-number-offset' in meta:
        secoffset = int(get_meta(meta, 'xnos-number-offset'))

def add_tex(meta):
    """Adds text to the meta data."""

    # pylint: disable=too-many-boolean-expressions
    warnings = warninglevel == 2 and (has_unnumbered_tables or \
      (targets and (pandocxnos.cleveref_required() or \
       separator_changed or plusname_changed or starname_changed \
       or has_tagged_tables or captionname_changed or numbersections \
       or secoffset)))
    if warnings:
        msg = textwrap.dedent("""\
                  pandoc-tablenos: Wrote the following blocks to
                  header-includes.  If you use pandoc's
                  --include-in-header option then you will need to
                  manually include these yourself.
              """)
        STDERR.write('\n')
        STDERR.write(textwrap.fill(msg))
        STDERR.write('\n')

    # Update the header-includes metadata.  Pandoc's
    # --include-in-header option will override anything we do here.  This
    # is a known issue and is owing to a design decision in pandoc.
    # See https://github.com/jgm/pandoc/issues/3139.

    if pandocxnos.cleveref_required() and targets:
        tex = """
            %%%% pandoc-tablenos: required package
            \\usepackage%s{cleveref}
        """ % ('[capitalise]' if capitalise else '')
        pandocxnos.add_to_header_includes(
            meta, 'tex', tex,
            regex=r'\\usepackage(\[[\w\s,]*\])?\{cleveref\}')

    if has_unnumbered_tables or (separator_changed and targets):
        tex = """
            %% pandoc-tablenos: required package
            \\usepackage{caption}
        """
        pandocxnos.add_to_header_includes(
            meta, 'tex', tex,
            regex=r'\\usepackage(\[[\w\s,]*\])?\{caption\}')

    if plusname_changed and targets:
        tex = """
            %%%% pandoc-tablenos: change cref names
            \\crefname{table}{%s}{%s}
        """ % (plusname[0], plusname[1])
        pandocxnos.add_to_header_includes(meta, 'tex', tex)

    if starname_changed and targets:
        tex = """
            %%%% pandoc-tablenos: change Cref names
            \\Crefname{table}{%s}{%s}
        """ % (starname[0], starname[1])
        pandocxnos.add_to_header_includes(meta, 'tex', tex)

    if has_unnumbered_tables:
        pandocxnos.add_to_header_includes(
            meta, 'tex', NO_PREFIX_CAPTION_ENV_TEX)

    if has_tagged_tables and targets:
        pandocxnos.add_to_header_includes(meta, 'tex', TAGGED_TABLE_ENV_TEX)

    if captionname_changed and targets:
        pandocxnos.add_to_header_includes(
            meta, 'tex', CAPTION_NAME_TEX % captionname)

    if separator_changed and targets:
        pandocxnos.add_to_header_includes(
            meta, 'tex', CAPTION_SEPARATOR_TEX % separator)

    if numbersections and targets:
        pandocxnos.add_to_header_includes(
            meta, 'tex', NUMBER_BY_SECTION_TEX)

    if secoffset and targets:
        pandocxnos.add_to_header_includes(
            meta, 'tex', SECOFFSET_TEX % secoffset,
            regex=r'\\setcounter\{section\}')

    if warnings:
        STDERR.write('\n')

# pylint: disable=too-many-locals, unused-argument
def main(stdin=STDIN, stdout=STDOUT, stderr=STDERR):
    """Filters the document AST."""

    # pylint: disable=global-statement
    global PANDOCVERSION
    global Table, AttrTable

    # Read the command-line arguments
    parser = argparse.ArgumentParser(\
      description='Pandoc table numbers filter.')
    parser.add_argument(\
      '--version', action='version',
      version='%(prog)s {version}'.format(version=__version__))
    parser.add_argument('fmt')
    parser.add_argument('--pandocversion', help='The pandoc version.')
    args = parser.parse_args()

    # Get the output format and document
    fmt = args.fmt
    doc = json.loads(stdin.read())

    # Initialize pandocxnos
    # pylint: disable=too-many-function-args
    PANDOCVERSION = pandocxnos.init(args.pandocversion, doc)

    # Element primitives
    AttrTable = elt('Table', 6)
    if version(PANDOCVERSION) >= version('2.10'):
        Table = elt('Table', 6)

    # Chop up the doc
    meta = doc['meta'] if version(PANDOCVERSION) >= version('1.18')\
      else doc[0]['unMeta']
    blocks = doc['blocks'] if version(PANDOCVERSION) >= version('1.18')\
      else doc[1:]

    # Process the metadata variables
    process(meta)

    # First pass
    detach_attrs_table = detach_attrs_factory(Table)
    insert_secnos = insert_secnos_factory(Table)
    delete_secnos = delete_secnos_factory(Table)
    actions = [attach_attrs_table, insert_secnos, process_tables, delete_secnos]
    if version(PANDOCVERSION) < version('2.10'):
        actions.append(detach_attrs_table)
    altered = functools.reduce(lambda x, action: walk(x, action, fmt, meta),
                               actions, blocks)

    # Second pass
    process_refs = process_refs_factory(LABEL_PATTERN, targets.keys())
    replace_refs = replace_refs_factory(targets,
                                        cleveref, False,
                                        plusname if not capitalise \
                                        or plusname_changed else
                                        [name.title() for name in plusname],
                                        starname)
    attach_attrs_span = attach_attrs_factory(Span, replace=True)
    altered = functools.reduce(lambda x, action: walk(x, action, fmt, meta),
                               [repair_refs, process_refs, replace_refs,
                                attach_attrs_span],
                               altered)

    if fmt in ['latex', 'beamer']:
        add_tex(meta)

    # Update the doc
    if version(PANDOCVERSION) >= version('1.18'):
        doc['blocks'] = altered
    else:
        doc = doc[:1] + altered

    # Dump the results
    json.dump(doc, stdout)

    # Flush stdout
    stdout.flush()

if __name__ == '__main__':
    main()
