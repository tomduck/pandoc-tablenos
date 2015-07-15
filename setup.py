"""setup.py - install script for pandoc-tablenos."""

import ez_setup
ez_setup.use_setuptools()

from setuptools import setup

LONG_DESCRIPTION = """\
pandoc-tablenos is a pandoc filter for numbering tables and table references.
"""

setup(
    name='pandoc-tablenos',
    version='0.2',

    author='Thomas J. Duck',
    author_email='tomduck@tomduck.ca',
    description='Table number filter for pandoc',
    long_description=LONG_DESCRIPTION,
    license='GPL',
    keywords='pandoc table numbers filter',
    url='https://github.com/tomduck/pandoc-tablenos',
    download_url = 'https://github.com/tomduck/pandoc-tablenos/tarball/0.2',
    
    install_requires=['pandocfilters', 'pandoc-attributes'],

    py_modules=['pandoc_tablenos'],
    entry_points={'console_scripts':['pandoc-tablenos = pandoc_tablenos:main']},

    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: End Users/Desktop',
        'Environment :: Console',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Programming Language :: Python'
        ],
)
