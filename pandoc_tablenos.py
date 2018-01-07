#! /usr/bin/env python

"""pandoc-tablenos: a pandoc filter that inserts table nos. and refs."""

# Copyright 2015-2018 Thomas J. Duck.
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

# pylint: disable=invalid-name

import re
import functools
import argparse
import json
import uuid

from pandocfilters import walk
from pandocfilters import Table, Str, Space, RawBlock, RawInline, Math

import pandocxnos
from pandocxnos import PandocAttributes
from pandocxnos import STRTYPES, STDIN, STDOUT
from pandocxnos import get_meta, extract_attrs
from pandocxnos import repair_refs, process_refs_factory, replace_refs_factory
from pandocxnos import insert_secnos_factory, delete_secnos_factory
from pandocxnos import detach_attrs_factory
from pandocxnos import insert_rawblocks_factory
from pandocxnos import elt


# Read the command-line arguments
parser = argparse.ArgumentParser(description='Pandoc table numbers filter.')
parser.add_argument('fmt')
parser.add_argument('--pandocversion', help='The pandoc version.')
args = parser.parse_args()

# Patterns for matching labels and references
LABEL_PATTERN = re.compile(r'(tbl:[\w/-]*)')

Nreferences = 0        # Global references counter
references = {}        # Global references tracker
unreferenceable = []   # List of labels that are unreferenceable

# Meta variables; may be reset elsewhere
captionname = 'Table'             # Used with \tablename
plusname = ['table', 'tables']    # Used with \cref
starname = ['Table', 'Tables']  # Used with \Cref
cleveref_default = False        # Default setting for clever referencing

# Flag for unnumbered tables
has_unnumbered_tables = False

# Variables for tracking section numbers
numbersections = False
cursec = None

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
            value.insert(0, attrs)
        except (ValueError, IndexError):
            pass

# pylint: disable=too-many-branches
def _process_table(value, fmt):
    """Processes the table.  Returns a dict containing table properties."""

    # pylint: disable=global-statement
    global Nreferences            # Global references counter
    global has_unnumbered_tables  # Flags unnumbered tables were found
    global cursec                 # Current section

    # Parse the table
    attrs, caption = value[:2]

    # Initialize the return value
    table = {'is_unnumbered': False,
             'is_unreferenceable': False,
             'is_tagged': False,
             'attrs': attrs}

    # Bail out if the label does not conform
    if not LABEL_PATTERN.match(attrs[0]):
        has_unnumbered_tables = True
        table['is_unnumbered'] = True
        table['is_unreferenceable'] = True
        return table

    # Process unreferenceable tables
    if attrs[0] == 'tbl:': # Make up a unique description
        attrs[0] = 'tbl:' + str(uuid.uuid4())
        table['is_unreferenceable'] = True
        unreferenceable.append(attrs[0])

    # For html, hard-code in the section numbers as tags
    kvs = PandocAttributes(attrs, 'pandoc').kvs
    if numbersections and fmt in ['html', 'html5'] and not 'tag' in kvs:
        if kvs['secno'] != cursec:
            cursec = kvs['secno']
            Nreferences = 1
        kvs['tag'] = cursec + '.' + str(Nreferences)
        Nreferences += 1

    # Save to the global references tracker
    table['is_tagged'] = 'tag' in kvs
    if table['is_tagged']:
        # Remove any surrounding quotes
        if kvs['tag'][0] == '"' and kvs['tag'][-1] == '"':
            kvs['tag'] = kvs['tag'].strip('"')
        elif kvs['tag'][0] == "'" and kvs['tag'][-1] == "'":
            kvs['tag'] = kvs['tag'].strip("'")
        references[attrs[0]] = kvs['tag']
    else:
        Nreferences += 1
        references[attrs[0]] = Nreferences

    # Adjust caption depending on the output format
    if fmt in['latex', 'beamer']:
        if not table['is_unreferenceable']:
            value[1] += [RawInline('tex', r'\label{%s}'%attrs[0])]
    else:  # Hard-code in the caption name and number/tag
        if type(references[attrs[0]]) is int:
            value[1] = [RawInline('html', r'<span>'),
                        Str(captionname), Space(),
                        Str('%d:'%references[attrs[0]]),
                        RawInline('html', r'</span>')] \
                if fmt in ['html', 'html5'] else \
                    [Str(captionname), Space(),
                     Str('%d:'%references[attrs[0]])]
            value[1] += [Space()] + list(caption)
        else:  # Tagged reference
            assert type(references[attrs[0]]) in STRTYPES
            text = references[attrs[0]]
            if text.startswith('$') and text.endswith('$'):
                math = text.replace(' ', r'\ ')[1:-1]
                els = [Math({"t":"InlineMath", "c":[]}, math), Str(':')]
            else:
                els = [Str(text + ':')]
            value[1] = \
                [RawInline('html', r'<span>'), Str(captionname), Space()] + \
                els + [RawInline('html', r'</span>')] \
                if fmt in ['html', 'html5'] else \
                [Str(captionname), Space()] + els

            value[1] += [Space()] + list(caption)

    return table

# pylint: disable=unused-argument
def process_tables(key, value, fmt, meta):
    """Processes the attributed tables."""

    global has_unnumbered_tables  # pylint: disable=global-statement

    # Process block-level Table elements
    if key == 'Table':

        # Inspect the table
        if len(value) == 5:  # Unattributed, bail out
            has_unnumbered_tables = True
            if fmt in ['latex']:
                return [RawBlock('tex', r'\begin{no-prefix-table-caption}'),
                        Table(*value),  # pylint: disable=star-args
                        RawBlock('tex', r'\end{no-prefix-table-caption}')]
            else:
                return

        # Process the table
        table = _process_table(value, fmt)

        # Context-dependent output
        attrs = table['attrs']
        if table['is_unnumbered']:
            if fmt in ['latex']:
                return [RawBlock('tex', r'\begin{no-prefix-table-caption}'),
                        AttrTable(*value),  # pylint: disable=star-args
                        RawBlock('tex', r'\end{no-prefix-table-caption}')]

        elif fmt in ['latex']:
            if table['is_tagged']:  # Code in the tags
                tex = '\n'.join([r'\let\oldthetable=\thetable',
                                 r'\renewcommand\thetable{%s}'%\
                                 references[attrs[0]]])
                pre = RawBlock('tex', tex)
                tex = '\n'.join([r'\let\thetable=\oldthetable',
                                 r'\addtocounter{table}{-1}'])
                post = RawBlock('tex', tex)
                # pylint: disable=star-args
                return [pre, AttrTable(*value), post]
        elif table['is_unreferenceable']:
            attrs[0] = ''  # The label isn't needed any further
        elif fmt in ('html', 'html5') and LABEL_PATTERN.match(attrs[0]):
            # Insert anchor
            anchor = RawBlock('html', '<a name="%s"></a>'%attrs[0])
            # pylint: disable=star-args
            return [anchor, AttrTable(*value)]
        elif fmt == 'docx':
            # As per http://officeopenxml.com/WPhyperlink.php
            bookmarkstart = \
              RawBlock('openxml',
                       '<w:p><w:bookmarkStart w:id="0" w:name="%s"/><w:r><w:t>'
                       %attrs[0])
            bookmarkend = \
              RawBlock('openxml', '</w:t></w:r><w:bookmarkEnd w:id="0"/></w:p>')
            # pylint: disable=star-args
            return [bookmarkstart, AttrTable(*value), bookmarkend]



# Main program ---------------------------------------------------------------

# Define \LT@makenoprefixcaption to make a caption without a prefix.  This
# should replace \@makecaption as needed.  See the standard \@makecaption TeX
# at https://stackoverflow.com/questions/2039690.  The macro gets installed
# using an environment.  The \thetable counter must be set to something unique
# so that duplicate names are avoided.  This must be done the hyperref
# counter \theHtable as well; see Sect. 3.9 of
# http://ctan.mirror.rafal.ca/macros/latex/contrib/hyperref/doc/manual.html.

TEX0 = r"""
% pandoc-xnos: macro to create a caption without a prefix
\makeatletter
\def\LT@makenoprefixcaption#1#2#3{%
  \LT@mcol\LT@cols c{\hbox to\z@{\hss\parbox[t]\LTcapwidth{
    \sbox\@tempboxa{#1{}#3}
    \ifdim\wd\@tempboxa>\hsize
      #1{}#3
    \else
      \hbox to\hsize{\hfil\box\@tempboxa\hfil}%
    \fi
    \endgraf\vskip\baselineskip}
  \hss}}}
\makeatother
""".strip()

TEX1 = r"""
% pandoc-tablenos: save original macros
\makeatletter
\let\LT@oldmakecaption=\LT@makecaption
\let\oldthetable=\thetable
\let\oldtheHtable=\theHtable
\makeatother
""".strip()

TEX2 = r"""
% pandoc-tablenos: environment disables table caption prefixes
\makeatletter
\newcounter{tableno}
\newenvironment{no-prefix-table-caption}{
  \let\LT@makecaption=\LT@makenoprefixcaption
  \renewcommand\thetable{x.\thetableno}
  \renewcommand\theHtable{x.\thetableno}
  \stepcounter{tableno}
}{
  \let\thetable=\oldthetable
  \let\theHtable=\oldtheHtable
  \let\LT@makecaption=\LT@oldmakecaption
  \addtocounter{table}{-1}
}
\makeatother
""".strip()

# TeX to set the caption name
TEX3 = r"""
%% pandoc-tablenos: caption name
\renewcommand{\tablename}{%s}
""".strip()

def process(meta):
    """Saves metadata fields in global variables and returns a few
    computed fields."""

    # pylint: disable=global-statement
    global captionname, cleveref_default, plusname, starname, numbersections

    # Read in the metadata fields and do some checking

    if 'tablenos-caption-name' in meta:
        captionname = get_meta(meta, 'tablenos-caption-name')
        assert type(captionname) in STRTYPES

    if 'cleveref' in meta:
        cleveref_default = get_meta(meta, 'cleveref')
        assert cleveref_default in [True, False]

    if 'tablenos-cleveref' in meta:
        cleveref_default = get_meta(meta, 'tablenos-cleveref')
        assert cleveref_default in [True, False]

    if 'tablenos-plus-name' in meta:
        tmp = get_meta(meta, 'tablenos-plus-name')
        if type(tmp) is list:
            plusname = tmp
        else:
            plusname[0] = tmp
        assert len(plusname) == 2
        for name in plusname:
            assert type(name) in STRTYPES

    if 'tablenos-star-name' in meta:
        tmp = get_meta(meta, 'tablenos-star-name')
        if type(tmp) is list:
            starname = tmp
        else:
            starname[0] = tmp
        assert len(starname) == 2
        for name in starname:
            assert type(name) in STRTYPES

    if 'xnos-number-sections' in meta and meta['xnos-number-sections']['c']:
        numbersections = True


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
    process_refs = process_refs_factory(references.keys())
    replace_refs = replace_refs_factory(references, cleveref_default,
                                        plusname, starname, 'table')
    altered = functools.reduce(lambda x, action: walk(x, action, fmt, meta),
                               [repair_refs, process_refs, replace_refs],
                               altered)

    # Insert supporting TeX
    if fmt in ['latex']:

        rawblocks = []

        if has_unnumbered_tables:
            rawblocks += [RawBlock('tex', TEX0),
                          RawBlock('tex', TEX1),
                          RawBlock('tex', TEX2)]

        if captionname != 'Table':
            rawblocks += [RawBlock('tex', TEX3 % captionname)]

        insert_rawblocks = insert_rawblocks_factory(rawblocks)

        altered = functools.reduce(lambda x, action: walk(x, action, fmt, meta),
                                   [insert_rawblocks], altered)

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
