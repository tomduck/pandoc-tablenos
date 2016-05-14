---
tablenos-plus-name: TAB.
tablenos-star-name: TABLE
...

*@tbl:1 and +@tbl:2, Tables {@tbl:1}-{@tbl:3} and Tables {@tbl:1}-{@tbl:2}-{@tbl:3}.


***


  Right     Left     Center     Default
-------     ------ ----------   -------
     12     12        12            12
    123     123       123          123
      1     1          1             1

Table: A simple table. Ref to +@tbl:2. {#tbl:1}


****


A B
- -
0 1

Table: Even simpler. {#tbl:2}


****


References in lists:

  * {*@tbl:1} and +@tbl:2
  * Tables {@tbl:1}-{@tbl:3} and Tables {@tbl:1}-{@tbl:2}-{@tbl:3}.


****


X Y
- -
0 1

Table: Just as simple. {#tbl:3}


****


An unreferenceable table:

X Y
- -
0 1

Table: Cannot be referenced. {#tbl:}


****


A [regular link](http://example.com/), an [*italicized link*](http://example.com/) and an email.address@mailinator.com.


\newpage


--------------------------------------------------------------------

Corner Cases
------------


Here is a table with no attributes.  This should not be numbered, but is for tex/pdf (a bug).

X Y
- -
0 1

Table: Another one.


****


Similarly, a table with empty attributes should not be numbered, but is for tex/pdf (a bug).

X Y
- -
0 1

Table: Another one. {}


****


Below is a series of three unreferenceable numbered tables.  Make sure the numbers are incrementing.

X Y
- -
0 1

Table: Another one. {#tbl:}


X Y
- -
0 1

Table: Another one. {#tbl:}


X Y
- -
0 1

Table: Another one. {#tbl:}
