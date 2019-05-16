---
tablenos-caption-name: TABLE
tablenos-plus-name: TAB.
tablenos-star-name: TABLE
...

*@tbl:1 and +@tbl:2, Tables {@tbl:1}-{@tbl:3} and Tables {@tbl:1}-{@tbl:2}-{@tbl:3}.

[*@tbl:1.]{style="color:red"}

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


An unnumbered table with no attributes:

X Y
- -
0 1

Table: Another one.


****


An unnumbered table with empty attributes:

X Y
- -
0 1

Table: Another one. {}


\newpage


****

Tables @tbl:4 and @tbl:5 are tagged tables:

X Y
- -
0 1

Table: Another one. {#tbl:4 tag="B.1"}


X Y
- -
0 1

Table: Another one. {#tbl:5 tag="$\text{B.3}'$"}


\newpage


****


A series of three unreferenceable numbered tables:

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
