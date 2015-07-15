
pandoc-tablenos
=============

*pandoc-tablenos* is a [pandoc] filter for numbering tables and table references.

Demonstration: Using [`demo.md`] as input gives output files in [pdf], [tex], [html], [epub], [md] and other formats.

This version of pandoc-tablenos was tested using pandoc 1.15.0.5 and is known to work under linux, Mac OS X and Windows.

See also: [pandoc-fignos], [pandoc-eqnos]

[pandoc]: http://pandoc.org/
[`demo.md`]: https://raw.githubusercontent.com/tomduck/pandoc-tablenos/master/demos/demo.md
[pdf]: https://raw.githubusercontent.com/tomduck/pandoc-tablenos/master/demos/out/demo.pdf
[tex]: https://raw.githubusercontent.com/tomduck/pandoc-tablenos/master/demos/out/demo.tex
[html]: https://rawgit.com/tomduck/pandoc-tablenos/master/demos/out/demo.html
[epub]: https://raw.githubusercontent.com/tomduck/pandoc-tablenos/master/demos/out/demo.epub
[md]: https://github.com/tomduck/pandoc-tablenos/blob/master/demos/out/demo.md
[pandoc-fignos]: https://github.com/tomduck/pandoc-fignos 
[pandoc-eqnos]: https://github.com/tomduck/pandoc-eqnos 


Contents
--------

 1. [Rationale](#rationale)
 2. [Markdown Syntax](#markdown-syntax)
 3. [Usage](#usage)
 4. [Details](#details)
 5. [Installation](#installation)
 6. [Getting Help](#getting-help)


Rationale
---------

Table numbers and references are required for academic writing, but are not currently supported by pandoc.  It is anticipated that this will eventually change.  Pandoc-tablenos is a transitional package for those who need table numbers and references now.

The syntax for table numbers and references was worked out in [pandoc issue #813].  It seems likely that this will be close to what pandoc ultimately adopts.

By doing one thing -- and one thing only -- my hope is that pandoc-tablenos will permit a relatively painless switch when pandoc provides native support for table numbers and references.

Installation of the filter is straight-forward, with minimal dependencies.  It is simple to use and has been tested extensively.

[pandoc issue #813]: https://github.com/jgm/pandoc/issues/813


Markdown Syntax
---------------

To tag a table caption with the label `tbl:description`, use

    Table: Caption. {#tbl:description}

The prefix `#tbl:` is required whereas `description` can be replaced with any combination of letters, numbers, dashes, slashes and underscores.

To reference the table, use

    @tbl:description

or

    {@tbl:description}

Curly braces around a reference are stripped from the output.


Usage
-----

To apply the filter, use the following option with pandoc:

    --filter pandoc-tablenos

Note that any use of the `--filter pandoc-citeproc` or `--bibliography=FILE` options with pandoc should come *after* the pandoc-tablenos filter call.


Details
-------

For tex/pdf output, LaTeX's native `\label` and `\ref` macros are used; for all others the numbers are hard-coded.

Links are not constructed -- just the table numbers.


Installation
------------

Pandoc-tablenos requires [python], a programming language that comes pre-installed on linux and Mac OS X, and which is easily installed [on Windows].  Either python 2.7 or 3.x will do.

Install pandoc-tablenos as root using the bash command

    pip install pandoc-tablenos 

To upgrade to the most recent release, use

    pip install --upgrade pandoc-tablenos 

Pip is a script that downloads and installs modules from the Python Package Index, [PyPI].  It should come installed with your python distribution.  If you are running linux, pip may be bundled separately.  For example, on a Debian-based system (including Ubuntu), you can install it as root using

    apt-get update
    apt-get install python-pip

[python]: https://www.python.org/
[on Windows]: https://www.python.org/downloads/windows/
[PyPI]: https://pypi.python.org/pypi


Getting Help
------------

If you have any difficulties with pandoc-tablenos, please feel welcome to [file an issue] on github so that we can help.

[file an issue]: https://github.com/tomduck/pandoc-tablenos/issues
