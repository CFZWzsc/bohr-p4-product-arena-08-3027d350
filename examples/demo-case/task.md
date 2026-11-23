# Demo task

Parse the synthetic paper material in the same directory into a structured result:

- body text in reading order, with page/block locators;
- section hierarchy with numbering;
- Table 1 with column names and cell-level locations;
- Figure 1 and its caption location;
- Equation (1) with symbols preserved;
- reference entries.

Every extracted item must carry a page/paragraph/block location and a verbatim
quote. Anything that cannot be read from the material must be reported as an
uncertainty instead of being guessed. This is a synthetic example, not official
case output.
