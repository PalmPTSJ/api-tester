# APT language

## Statement
```
SECT [name:str*]
REQ  [method:str*]  [url:str*]  [data:expr]?
RES  [data:expr]
SET  [varname:str]  [data:expr]
```

# Data type and resolver

## Literal
```
obj_lit: {<YAML Data>}
str_lit: <any string>
```

Scanner scans parameters as a literal. For example
```
REQ  POST  http://url  {data: 123}

RequestStatement(
    "POST",         ; str_lit
    "http://url",   ; str_lit
    {data:123}      ; obj_lit
)
```

---
## Expression (Expr)
```
expr:  str_lit | obj_lit | expr bin_op expr | (expr)
```

---
## Type

Primitive types: int, float, str, obj
```
int:    e.g., 1, -50, 999
float:  e.g., 1.0, -5.5
str:    e.g., "test", "a string here" (without quotes)
obj:    e.g., {"xx": "yy"}
```

Extended types: var, at_var, template_str
```
var:            e.g., $var, $xxx
at_var:         e.g., @file:data, @:, @dir/file.txt:data.nested
template_str:   e.g., "Template string: ${var}"
```

---
## Resolve
```
Note:   *x = resolve(x)
        x* = Any types that can be resolved to x

*expr -> *str_lit           ; if expr = str_lit
        | *obj_lit           ; if expr = obj_lit
        | *expr              ; if expr = expr bin_op expr  || expr = (expr)

*str_lit -> int             ; if in form [+-]\d+
            | float         ; if in form [+-]\d+\.\d*
            | *var          ; if starts with '$'
            | *at_var       ; if starts with '@'
            | *str          ; else

*str -> str                 ; Resolve template string
*obj_lit -> obj
*var -> str | int | float | obj
*at_var -> str | int | float | obj

str*: str_lit | str | int | float | obj     ; 
```

Before runner execute a statement, its parameters should be resolved against the runner's environment. Environment contains variables and their values.

Runner must manages its environment object.
