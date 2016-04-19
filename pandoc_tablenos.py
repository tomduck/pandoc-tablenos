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
# The basic idea is to scan the AST twice in order to:
#
#   1. Insert text for the table number in each table caption.
#      For LaTeX, insert \label{...} instead.  The table labels
#      and associated table numbers are stored in the global
#      references tracker.
#
#   2. Replace each reference with a table number.  For LaTeX,
#      replace with \ref{...} instead.
#
# There is also an initial scan to do some preprocessing.

# pylint: disable=invalid-name

import re
import functools
import itertools
import io
import sys
import os, os.path
import subprocess
import psutil
import argparse

# pylint: disable=import-error
import pandocfilters
from pandocfilters import stringify, walk
from pandocfilters import RawInline, Str, Space, Para, Plain, Cite, Table
from pandocattributes import PandocAttributes

# Read the command-line arguments
parser = argparse.ArgumentParser(description='Pandoc figure numbers filter.')
parser.add_argument('fmt')
parser.add_argument('--pandocversion', help='The pandoc version.')
args = parser.parse_args()

# Get the pandoc version.  Inspect the parent process first, then check the
# python command line args.
PANDOCVERSION = None
if os.name == 'nt':
    # psutil appears to work differently for windows.  Two parent calls?  Weird.
    command = psutil.Process(os.getpid()).parent().parent().exe()
else:
    command = psutil.Process(os.getpid()).parent().exe()
if 'tablenos' in command:  # Infinite process creation!
    raise RuntimeError('Could not find parent to pandoc-tablenos. ' \
                       'Please contact developer.')
if os.path.basename(command).startswith('pandoc'):
    output = subprocess.check_output([command, '-v'])
    line = output.decode('utf-8').split('\n')[0]
    PANDOCVERSION = line.split(' ')[-1]
else:
    if args.pandocversion:
        PANDOCVERSION = args.pandocversion
if PANDOCVERSION is None:
    raise RuntimeError('Cannot determine pandoc version.  '\
                       'Please file an issue at '\
                       'https://github.com/tomduck/pandoc-tablenos/issues')

# Detect python 3
PY3 = sys.version_info > (3,)

# Pandoc uses UTF-8 for both input and output; so must we
if PY3:  # Force utf-8 decoding (decoding of input streams is automatic in py3)
    STDIN = io.TextIOWrapper(sys.stdin.buffer, 'utf-8', 'strict')
    STDOUT = io.TextIOWrapper(sys.stdout.buffer, 'utf-8', 'strict')
else:    # No decoding; utf-8-encoded strings in means the same out
    STDIN = sys.stdin
    STDOUT = sys.stdout

# Patterns for matching attributes, labels and references.  This is a little
# different from pandoc-fignos and pandoc-tablenos.  The attributes appear in
# the caption string.
ATTR_PATTERN = re.compile(r'(.*)\{(.*)\}')
LABEL_PATTERN = re.compile(r'(tbl:[\w/-]*)')
REF_PATTERN = re.compile(r'@(tbl:[\w/-]+)')

references = {}  # Global references tracker

def is_attrtable(key, value):
    """True if this is an attributed table; False otherwise."""
    return key == 'Table' and len(value) == 6

def parse_attrtable(value):
    """Parses an attributed table."""
    # I am not sure what the purpose of x is.  It appears to be a list of
    # zeros with length equal to the width of the table.
    o, caption, align, x, head, body = value
    attrs = PandocAttributes(o, 'pandoc')
    if attrs.id == 'tbl:': # Make up a unique description
        attrs.id = 'tbl:' + '__'+str(hash(str(value[1:])))+'__'
    return attrs, caption, align, x, head, body

def is_tblref(key, value):
    """True if this is a table reference; False otherwise."""
    return key == 'Cite' and REF_PATTERN.match(value[1][0]['c']) and \
            parse_tblref(value)[1] in references

def parse_tblref(value):
    """Parses a table reference."""
    prefix = value[0][0]['citationPrefix']
    label = REF_PATTERN.match(value[1][0]['c']).groups()[0]
    suffix = value[0][0]['citationSuffix']
    return prefix, label, suffix

def ast(string):
    """Returns an AST representation of the string."""
    toks = [Str(tok) for tok in string.split()]
    spaces = [Space()]*len(toks)
    ret = list(itertools.chain(*zip(toks, spaces)))
    if string[0] == ' ':
        ret = [Space()] + ret
    return ret if string[-1] == ' ' else ret[:-1]

def is_broken_ref(key1, value1, key2, value2):
    """True if this is a broken link; False otherwise."""
    if PANDOCVERSION < '1.16':
        return key1 == 'Link' and value1[0][0]['t'] == 'Str' \
           and value1[0][0]['c'].endswith('{@tbl') \
            and key2 == 'Str' and '}' in value2
    else:
        return key1 == 'Link' and value1[1][0]['t'] == 'Str' \
          and value1[1][0]['c'].endswith('{@tbl') \
            and key2 == 'Str' and '}' in value2

def repair_broken_refs(value):
    """Repairs references broken by pandoc's --autolink_bare_uris."""

    # autolink_bare_uris splits {@tbl:label} at the ':' and treats
    # the first half as if it is a mailto url and the second half as a string.
    # Let's replace this mess with Cite and Str elements that we normally get.
    flag = False
    for i in range(len(value)-1):
        if value[i] == None:
            continue
        if is_broken_ref(value[i]['t'], value[i]['c'],
                         value[i+1]['t'], value[i+1]['c']):
            flag = True  # Found broken reference
            if PANDOCVERSION < '1.16':
                s1 = value[i]['c'][0][0]['c']  # Get the first half of the ref
            else:
                s1 = value[i]['c'][1][0]['c']  # Get the first half of the ref
            s2 = value[i+1]['c']           # Get the second half of the ref
            ref = '@tbl' + s2[:s2.index('}')]  # Form the reference
            prefix = s1[:s1.index('{@tbl')]    # Get the prefix
            suffix = s2[s2.index('}')+1:]      # Get the suffix
            # We need to be careful with the prefix string because it might be
            # part of another broken reference.  Simply put it back into the
            # stream and repeat the preprocess() call.
            if i > 0 and value[i-1]['t'] == 'Str':
                value[i-1]['c'] = value[i-1]['c'] + prefix
                value[i] = None
            else:
                value[i] = Str(prefix)
            # Put fixed reference in as a citation that can be processed
            value[i+1] = Cite(
                [{"citationId":ref[1:],
                  "citationPrefix":[],
                  "citationSuffix":[Str(suffix)],
                  "citationNoteNum":0,
                  "citationMode":{"t":"AuthorInText", "c":[]},
                  "citationHash":0}],
                [Str(ref)])
    if flag:
        return [v for v in value if not v is None]

def is_braced_tblref(i, value):
    """Returns true if a reference is braced; otherwise False.
    i is the index in the value list.
    """
    return is_tblref(value[i]['t'], value[i]['c']) \
      and value[i-1]['t'] == 'Str' and value[i+1]['t'] == 'Str' \
      and value[i-1]['c'].endswith('{') and value[i+1]['c'].startswith('}')

def remove_braces_from_tblrefs(value):
    """Search for references and remove curly braces around them."""
    flag = False
    for i in range(len(value)-1)[1:]:
        if is_braced_tblref(i, value):
            flag = True  # Found reference
            value[i-1]['c'] = value[i-1]['c'][:-1]  # Remove the braces
            value[i+1]['c'] = value[i+1]['c'][1:]
    return flag

# pylint: disable=unused-argument
def preprocess(key, value, fmt, meta):
    """Preprocesses to correct for problems."""
    if key in ('Para', 'Plain'):
        while True:
            newvalue = repair_broken_refs(value)
            if newvalue:
                value = newvalue
            else:
                break
        if key == 'Para':
            return Para(value)
        else:
            return Plain(value)

def deQuoted(value):
    """Replaces Quoted elements that stringify() can't handle."""
    # pandocfilters.stringify() needs to be updated...

    # The weird thing about this is that chained filters do not see this
    # element.  Pandoc gives different json depending on whether or it is
    # calling the filter directly.  This should not be happening.
    newvalue = []
    for v in value:
        if v['t'] != 'Quoted':
            newvalue.append(v)
        else:
            quote = '"' if v['c'][0]['t'] == 'DoubleQuote' else "'"
            newvalue.append(Str(quote))
            newvalue += v['c'][1]
            newvalue.append(Str(quote))
    return newvalue

def get_attrs(caption):
    """Extracts attributes from a list of elements.
    Extracted elements are set to None in the list.
    """
    # This is a little different from pandoc-fignos and pandoc-tablenos.
    # The attributes appear in the caption string.

    # Fix me: This currently does not allow curly braces inside quoted
    # attributes.  The close bracket is interpreted as the end of the attrs.

    # Set n to the index where the attributes start
    n = 0
    while n < len(caption) and not \
      (caption[n]['t'] == 'Str' and caption[n]['c'].startswith('{')):
        n += 1
    if caption[n:] and caption[-1]['t'] == 'Str' and \
      caption[-1]['c'].strip().endswith('}'):
        s = stringify(deQuoted(caption[n:]))  # Extract the attrs
        caption[n:] = [None]*(len(caption[n:]))  # Remove extracted elements
        return PandocAttributes(s.strip(), 'markdown')

# pylint: disable=unused-argument
def replace_attrtables(key, value, fmt, meta):
    """Replaces attributed tables while storing reference labels."""

    # Note: We cannot replace the table with an AttrTable because it would
    # not get reprocessed.  Tables are not enclosed by Para.  The attributes
    # are contained in the caption.
    if key == 'Table':

        # Parse the table
        caption, align, x, head, body = value
        attrs = get_attrs(caption)
        if attrs:
            caption = [v for v in caption if not v is None]

        # Bail out if the label does not conform
        if not attrs.id or not LABEL_PATTERN.match(attrs.id):
            return Table(caption, align, x, head, body)

        # Save the reference
        references[attrs.id] = len(references) + 1

        # Adjust caption depending on the output format
        if fmt == 'latex':
            caption += [RawInline('tex', r'\label{%s}'%attrs.id)]
        else:
            caption = ast('Table %d. '%references[attrs.id]) + caption

        # Return the replacement
        if fmt in ('html', 'html5'):
            anchor = RawInline('html', '<a name="%s"></a>'%attrs.id)
            return [Plain([anchor]), Table(caption, align, x, head, body)]
        else:
            return Table(caption, align, x, head, body)

# pylint: disable=unused-argument
def replace_refs(key, value, fmt, meta):
    """Replaces references to labelled tables."""

    # Remove braces around references
    if key in ('Para', 'Plain'):
        if remove_braces_from_tblrefs(value):
            if key == 'Para':
                return Para(value)
            else:
                return Plain(value)

    # Replace references
    if is_tblref(key, value):
        prefix, label, suffix = parse_tblref(value)
        # The replacement depends on the output format
        if fmt == 'latex':
            return prefix + [RawInline('tex', r'\ref{%s}'%label)] + suffix
        elif fmt in ('html', 'html5'):
            link = '<a href="#%s">%s</a>' % (label, references[label])
            return prefix + [RawInline('html', link)] + suffix
        else:
            return prefix + [Str('%d'%references[label])]+suffix

def main():
    """Filters the document AST."""

    # Get the output format, document and metadata
    fmt = args.fmt
    doc = pandocfilters.json.loads(STDIN.read())
    meta = doc[0]['unMeta']

    # Replace attributed tables and references in the AST
    altered = functools.reduce(lambda x, action: walk(x, action, fmt, meta),
                               [preprocess, replace_attrtables, replace_refs],
                               doc)

    # Dump the results
    pandocfilters.json.dump(altered, STDOUT)

    # Flush stdout
    STDOUT.flush()

if __name__ == '__main__':
    main()
