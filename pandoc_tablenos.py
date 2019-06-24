#! /usr/bin/env python

"""pandoc-tablenos: a pandoc filter that inserts table nos. and refs."""


__version__ = '2.0.0b1'


# Copyright 2015-2019 Thomas J. Duck.
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
#      references tracker.
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
from pandocxnos import check_bool, get_meta, extract_attrs
from pandocxnos import repair_refs, process_refs_factory, replace_refs_factory
from pandocxnos import insert_secnos_factory, delete_secnos_factory
from pandocxnos import attach_attrs_factory, detach_attrs_factory
from pandocxnos import elt


# Read the command-line arguments
parser = argparse.ArgumentParser(description='Pandoc table numbers filter.')
parser.add_argument('--version', action='version',
                    version='%(prog)s {version}'.format(version=__version__))
parser.add_argument('fmt')
parser.add_argument('--pandocversion', help='The pandoc version.')
args = parser.parse_args()

# Patterns for matching labels and references
LABEL_PATTERN = re.compile(r'(tbl:[\w/-]*)')

# Meta variables; may be reset elsewhere
captionname = 'Table'   # The caption name
cleveref = False        # Flags that clever references should be used
capitalise = False      # Default setting for capitalizing plusname
plusname = ['table', 'tables']  # Sets names for mid-sentence references
starname = ['Table', 'Tables']  # Sets names for references at sentence start
numbersections = False  # Flags that tables should be numbered by section
warninglevel = 1        # 0 - no warnings; 1 - some warnings; 2 - all warnings

# Processing state variables
cursec = None    # Current section
Nreferences = 0  # Number of references in current section (or document)
references = {}  # Maps reference labels to [number/tag, table secno]

# Processing flags
captionname_changed = False     # Flags the the caption name changed
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
    if key in ['Table']:
        assert len(value) == 5
        caption = value[0]  # caption, align, x, head, body

        # Set n to the index where the attributes start
        n = 0
        while n < len(caption) and not \
          (caption[n]['t'] == 'Str' and caption[n]['c'].startswith('{')):
            n += 1

        try:
            attrs = extract_attrs(caption, n)
            value.insert(0, attrs.list)
        except (ValueError, IndexError):
            pass

# pylint: disable=too-many-branches
def _process_table(value, fmt):
    """Processes the table.  Returns a dict containing table properties."""

    # pylint: disable=global-statement
    global cursec       # Current section being processed
    global Nreferences  # Number of refs in current section (or document)
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
    table['caption'] = value[1]

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
        Nreferences = 1           # Resets the global reference counter

    # Pandoc's --number-sections supports section numbering latex/pdf, html,
    # epub, and docx
    if numbersections:
        if fmt in ['html', 'html5', 'epub', 'epub2', 'epub3', 'docx'] and \
          'tag' not in attrs:
            attrs['tag'] = str(cursec) + '.' + str(Nreferences)
            Nreferences += 1

    # Save reference information
    table['is_tagged'] = 'tag' in attrs
    if table['is_tagged']:
        # Remove any surrounding quotes
        if attrs['tag'][0] == '"' and attrs['tag'][-1] == '"':
            attrs['tag'] = attrs['tag'].strip('"')
        elif attrs['tag'][0] == "'" and attrs['tag'][-1] == "'":
            attrs['tag'] = attrs['tag'].strip("'")
        references[attrs.id] = [attrs['tag'], cursec]
    else:  # ... then save the table number
        references[attrs.id] = [Nreferences, cursec]
        Nreferences += 1  # Increment the global reference counter

    return table


def _adjust_caption(fmt, table, value):
    """Adjusts the caption."""
    attrs, caption = table['attrs'], table['caption']
    if fmt in['latex', 'beamer']:  # Append a \label if this is referenceable
        if not table['is_unreferenceable']:
            value[1] += [RawInline('tex', r'\label{%s}'%attrs.id)]
    else:  # Hard-code in the caption name and number/tag
        if isinstance(references[attrs.id][0], int):  # Numbered reference
            if fmt in ['html', 'html5', 'epub', 'epub2', 'epub3']:
                value[1] = [RawInline('html', r'<span>'),
                            Str(captionname), Space(),
                            Str('%d:'%references[attrs.id][0]),
                            RawInline('html', r'</span>')]
            else:
                value[1] = [Str(captionname),
                            Space(),
                            Str('%d:'%references[attrs.id][0])]
            value[1] += [Space()] + list(caption)
        else:  # Tagged reference
            assert isinstance(references[attrs.id][0], STRTYPES)
            text = references[attrs.id][0]
            if text.startswith('$') and text.endswith('$'):
                math = text.replace(' ', r'\ ')[1:-1]
                els = [Math({"t":"InlineMath", "c":[]}, math), Str(':')]
            else:  # Text
                els = [Str(text + ':')]
            if fmt in ['html', 'html5', 'epub', 'epub2', 'epub3']:
                value[1] = \
                  [RawInline('html', r'<span>'),
                   Str(captionname),
                   Space()] + els + [RawInline('html', r'</span>')]
            else:
                value[1] = [Str(captionname), Space()] + els
            value[1] += [Space()] + list(caption)


def _add_markup(fmt, table, value):
    """Adds markup to the output."""

    # pylint: disable=global-statement
    global has_tagged_tables  # Flags a tagged tables was found

    if table['is_unnumbered']:
        if fmt in ['latex', 'beamer']:
            # Use the no-prefix-table-caption environment
            return [RawBlock('tex',
                             r'\begin{tablenos:no-prefix-table-caption}'),
                    Table(*(value if len(value)==5 else value[1:])),
                    RawBlock('tex', r'\end{tablenos:no-prefix-table-caption}')]
        return None  # Nothing to do

    attrs = table['attrs']
    ret = None

    if fmt in ['latex', 'beamer']:
        if table['is_tagged']:  # A table cannot be tagged if it is unnumbered
            has_tagged_tables = True
            ret = [RawBlock('tex', r'\begin{tablenos:tagged-table}[%s]' % \
                            references[attrs.id][0]),
                   AttrTable(*value),
                   RawBlock('tex', r'\end{tablenos:tagged-table}')]
    elif fmt in ('html', 'html5', 'epub', 'epub2', 'epub3'):
        if LABEL_PATTERN.match(attrs.id):
            # Insert anchor
            anchor = RawBlock('html', '<a name="%s"></a>'%attrs.id)
            ret = [anchor, AttrTable(*value)]
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


# Main program ---------------------------------------------------------------

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

# Define some tex to number tables by section
NUMBER_BY_SECTION_TEX = r"""
%% pandoc-tablenos: number tables by section
\numberwithin{table}{section}
"""


# Main program ---------------------------------------------------------------

# pylint: disable=too-many-branches,too-many-statements
def process(meta):
    """Saves metadata fields in global variables and returns a few
    computed fields."""

    # pylint: disable=global-statement
    global captionname     # The caption name
    global cleveref        # Flags that clever references should be used
    global capitalise      # Flags that plusname should be capitalised
    global plusname        # Sets names for mid-sentence references
    global starname        # Sets names for references at sentence start
    global numbersections  # Flags that sections should be numbered by section
    global warninglevel    # 0 - no warnings; 1 - some; 2 - all
    global captionname_changed  # Flags the the caption name changed
    global plusname_changed     # Flags that the plus name changed
    global starname_changed     # Flags that the star name changed

    # Read in the metadata fields and do some checking

    for name in ['tablenos-warning-level', 'xnos-warning-level']:
        if name in meta:
            warninglevel = int(get_meta(meta, name))
            break

    metanames = ['tablenos-warning-level', 'xnos-warning-level',
                 'tablenos-caption-name',
                 'tablenos-cleveref', 'xnos-cleveref',
                 'xnos-capitalise', 'xnos-capitalize',
                 'tablenos-plus-name', 'tablenos-star-name',
                 'tablenos-number-sections', 'xnos-number-sections']

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

    for name in ['tablenos-number-sections', 'xnos-number-sections']:
        if name in meta:
            numbersections = check_bool(get_meta(meta, name))
            break


def add_tex(meta):
    """Adds text to the meta data."""

    # pylint: disable=too-many-boolean-expressions
    warnings = warninglevel == 2 and  references and \
      (pandocxnos.cleveref_required() or has_unnumbered_tables or
       plusname_changed or starname_changed or has_tagged_tables or
       captionname != 'Table' or numbersections)
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

    if pandocxnos.cleveref_required() and references:
        tex = """
            %%%% pandoc-tablenos: required package
            \\usepackage%s{cleveref}
        """ % ('[capitalise]' if capitalise else '')
        pandocxnos.add_tex_to_header_includes(
            meta, tex, warninglevel, r'\\usepackage(\[[\w\s,]*\])?\{cleveref\}')

    if has_unnumbered_tables and references:
        tex = """
            %%%% pandoc-tablenos: required package
            \\usepackage{caption}
        """
        pandocxnos.add_tex_to_header_includes(
            meta, tex, warninglevel, r'\\usepackage(\[[\w\s,]*\])?\{caption\}')

    if plusname_changed and references:
        tex = """
            %%%% pandoc-tablenos: change cref names
            \\crefname{table}{%s}{%s}
        """ % (plusname[0], plusname[1])
        pandocxnos.add_tex_to_header_includes(meta, tex, warninglevel)

    if starname_changed and references:
        tex = """\
            %%%% pandoc-tablenos: change Cref names
            \\Crefname{table}{%s}{%s}
        """ % (starname[0], starname[1])
        pandocxnos.add_tex_to_header_includes(meta, tex, warninglevel)

    if has_unnumbered_tables and references:
        pandocxnos.add_tex_to_header_includes(
            meta, NO_PREFIX_CAPTION_ENV_TEX, warninglevel)

    if has_tagged_tables and references:
        pandocxnos.add_tex_to_header_includes(
            meta, TAGGED_TABLE_ENV_TEX, warninglevel)

    if captionname != 'Table' and references:
        pandocxnos.add_tex_to_header_includes(
            meta, CAPTION_NAME_TEX % captionname, warninglevel)

    if numbersections and references:
        pandocxnos.add_tex_to_header_includes(
            meta, NUMBER_BY_SECTION_TEX, warninglevel)

    if warnings:
        STDERR.write('\n')


def main():
    """Filters the document AST."""

    # pylint: disable=global-statement
    global PANDOCVERSION
    global AttrTable

    # Get the output format and document
    fmt = args.fmt
    doc = json.loads(STDIN.read())

    # Initialize pandocxnos
    # pylint: disable=too-many-function-args
    PANDOCVERSION = pandocxnos.init(args.pandocversion, doc)

    # Element primitives
    AttrTable = elt('Table', 6)

    # Chop up the doc
    meta = doc['meta'] if PANDOCVERSION >= '1.18' else doc[0]['unMeta']
    blocks = doc['blocks'] if PANDOCVERSION >= '1.18' else doc[1:]

    # Process the metadata variables
    process(meta)

    # First pass
    detach_attrs_table = detach_attrs_factory(Table)
    insert_secnos = insert_secnos_factory(Table)
    delete_secnos = delete_secnos_factory(Table)
    altered = functools.reduce(lambda x, action: walk(x, action, fmt, meta),
                               [attach_attrs_table, insert_secnos,
                                process_tables, delete_secnos,
                                detach_attrs_table], blocks)

    # Second pass
    process_refs = process_refs_factory('pandoc-tablenos', references.keys(),
                                        warninglevel)
    replace_refs = replace_refs_factory(references,
                                        cleveref, False,
                                        plusname if not capitalise \
                                        or plusname_changed else
                                        [name.title() for name in plusname],
                                        starname)
    attach_attrs_span = attach_attrs_factory('pandoc-tablenos', Span,
                                             warninglevel, replace=True)
    altered = functools.reduce(lambda x, action: walk(x, action, fmt, meta),
                               [repair_refs, process_refs, replace_refs,
                                attach_attrs_span],
                               altered)

    if fmt in ['latex', 'beamer']:
        add_tex(meta)

    # Update the doc
    if PANDOCVERSION >= '1.18':
        doc['blocks'] = altered
    else:
        doc = doc[:1] + altered

    # Dump the results
    json.dump(doc, STDOUT)

    # Flush stdout
    STDOUT.flush()

if __name__ == '__main__':
    main()
