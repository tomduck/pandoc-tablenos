#! /usr/bin/env python

"""pandoc-tablenos: a pandoc filter that inserts table nos. and refs."""

# Copyright 2015, 2016 Thomas J. Duck.
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

from pandocfilters import walk, elt
from pandocfilters import Table, Str, Space, RawBlock, RawInline

import pandocxnos
from pandocxnos import STRTYPES, STDIN, STDOUT
from pandocxnos import get_meta, extract_attrs
from pandocxnos import repair_refs, process_refs_factory, replace_refs_factory
from pandocxnos import detach_attrs_factory


# Read the command-line arguments
parser = argparse.ArgumentParser(description='Pandoc table numbers filter.')
parser.add_argument('fmt')
parser.add_argument('--pandocversion', help='The pandoc version.')
args = parser.parse_args()

# Initialize pandocxnos
PANDOCVERSION = pandocxnos.init(args.pandocversion)

# Patterns for matching labels and references
LABEL_PATTERN = re.compile(r'(tbl:[\w/-]*)')

references = {}  # Global references tracker

# Meta variables; may be reset elsewhere
plusname = ['table', 'tables']    # Used with \cref
starname = ['Table', 'Tables']  # Used with \Cref
cleveref_default = False        # Default setting for clever referencing


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

detach_attrs_table = detach_attrs_factory(Table)

# pylint: disable=unused-argument
def process_tables(key, value, fmt, meta):
    """Processes the attributed tables."""

    if key == 'Table' and len(value) == 6:

        # Parse the table
        attrs, caption = value[0:2]  # attrs, caption, align, x, head, body

        # Bail out if the label does not conform
        if not attrs[0] or not LABEL_PATTERN.match(attrs[0]):
            return

        if attrs[0] == 'tbl:': # Make up a unique description
            attrs[0] = 'tbl:' + str(uuid.uuid4())

        # Save the reference
        references[attrs[0]] = len(references) + 1

        # Adjust caption depending on the output format
        if fmt == 'latex':
            value[1] += [RawInline('tex', r'\label{%s}'%attrs[0])]
        else:
            value[1] = [Str('Table'), Space(),
                        Str('%d.'%references[attrs[0]]), Space()] + \
                        list(caption)

        if fmt in ('html', 'html5'):  # Insert anchor
            table = elt('Table', 6)(*value) # pylint: disable=star-args
            table['c'] = list(table['c'])  # Needed for attr filtering
            anchor = RawBlock('html', '<a name="%s"></a>'%attrs[0])
            return [anchor, table]


# Main program ---------------------------------------------------------------

def process(meta):
    """Saves metadata fields in global variables and returns a few
    computed fields."""

    # pylint: disable=global-statement
    global cleveref_default, plusname, starname

    # Read in the metadata fields and do some checking

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


def main():
    """Filters the document AST."""

    # Get the output format, document and metadata
    fmt = args.fmt
    doc = json.loads(STDIN.read())
    meta = doc[0]['unMeta']

    # Process the metadata variables
    process(meta)

    # First pass
    altered = functools.reduce(lambda x, action: walk(x, action, fmt, meta),
                               [attach_attrs_table, process_tables,
                                detach_attrs_table], doc)

    # Second pass
    process_refs = process_refs_factory(references.keys())
    replace_refs = replace_refs_factory(references, cleveref_default,
                                        plusname, starname, 'table')
    altered = functools.reduce(lambda x, action: walk(x, action, fmt, meta),
                               [repair_refs, process_refs, replace_refs],
                               altered)

    # Dump the results
    json.dump(altered, STDOUT)

    # Flush stdout
    STDOUT.flush()

if __name__ == '__main__':
    main()
