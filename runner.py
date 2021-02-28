import sys
import os
import typing
import enum
import requests
import json
import yaml
import re
from datetime import datetime

def accessObj(obj: dict, accessor: str):
    if accessor == "":              
        return obj
    def access(obj, fields):
        if obj == None:             return None
        if fields[0] not in obj:    return None
        if len(fields) == 1:        return obj[fields[0]]
        return access(obj[fields[0]], fields[1:])
    return access(obj,accessor.split("."))

def normalizeVarname(name):
    return "$" + name if name[0:1] != "$" else name

class APTEnv():
    """ Base Environment manager """
    def __init__(self):             self.vars, self.at = ({}, None)
    def setVar(self, varname, val): self.vars[normalizeVarname(varname)] = val
    def getVar(self, varname):      return None if normalizeVarname(varname) not in self.vars else self.vars[normalizeVarname(varname)]
    def setAtVar(self, val):        self.at = val
    def getAtVar(self):             return self.at

class APT() :
    class Token():
        REQ = "REQ"
        SECT = "SECT"
        RES = "RES"
        SET = "SET"

    class Expr():
        class Base():
            def __init__(self, val):    self.val = val
            def __str__(self):          return str(self.val)
            def resolve(self, env):     return self.val
        class Null(Base): pass
        class Object(Base): pass # TODO: Recursively resolve value
        class String(Base): pass
        class Int(Base): pass
        class Float(Base): pass
        class StringLit(Base):
            def deriveType(self):
                lit = self.val.strip()
                if re.match("[+-]\\d+", lit):           return APT.Expr.Int(int(lit))
                elif re.match("[+-]\\d+\\.\\d*", lit):  return APT.Expr.Float(float(lit))
                elif len(lit) == 0:                     return APT.Expr.Null(None)
                elif lit[0] == "@":                     return APT.Expr.AtVar(lit)
                elif lit[0] == "$":                     return APT.Expr.Var(lit)
                else:                                   return APT.Expr.String(lit)
            def resolve(self, env):
                return self.deriveType().resolve(env)
        class AtVar(Base): # @<file>:<accessor>. Ex: @template:data, @:, 
            def resolve(self, env:APTEnv):
                fname, accessor = self.val[1:].strip().split(":")
                # TODO: Resolve filename and path smarter, cache file, add loaded data to env
                def do(data):
                    val = accessObj(data, accessor)
                    if isinstance(val, dict):       return APT.Expr.Object(val).resolve(env)
                    elif isinstance(val, str):      return APT.Expr.String(val).resolve(env)
                    elif isinstance(val, int):      return APT.Expr.Int(val).resolve(env)
                    elif isinstance(val, float):    return APT.Expr.Float(val).resolve(env)
                    else:                           return APT.Expr.Base(val).resolve(env)
                if fname == "":
                    return do(env.getAtVar())
                if not os.path.exists(fname) or not os.path.isfile(fname):
                    return None
                with open(fname, "r") as f:
                    data = yaml.safe_load(f)
                    env.setAtVar(data)
                    return do(data)
        class Var(Base):
            def __init__(self, val):        self.val = val
            def resolve(self, env:APTEnv):  return env.getVar(self.val)
        class BinOp(Base):
            def __str__(self):                      return "%s %s %s" % (self.left, self.op, self.right)
            def __init__(self, op, left, right):    self.op, self.left, self.right = op, left, right
            def resolve(self, env): 
                self.left = self.left.resolve(env)
                self.right = self.right.resolve(env)
                if self.op == "+":
                    if isinstance(self.left, dict) and isinstance(self.right, dict):
                        data = self.left
                        data.update(self.right)
                        return data
                    return self.left + self.right

    class Statement():
        class Section():
            def __init__(self, name:str):                                   self.name = name
            def __str__(self):                                              return "SECT <%s>" % (self.name)
        class Request():
            def __init__(self, method:str, url:str, data:'APT.Expr.Base'):  self.method, self.url, self.data = method, url, data
            def __str__(self):                                              return "REQ <%s> <%s> <%s>" % (self.method, self.url, self.data)
        class Response():
            def __init__(self, data:'APT.Expr.Base'):                       self.data = data
            def __str__(self):                                              return "RES <%s>" % (self.data)
        class Set():
            def __init__(self, varname:str, data:'APT.Expr.Base'):          self.varname, self.data = varname, data
            def __str__(self):                                              return "SET <%s> <%s>" % (self.varname, self.data)
    
    class Scanner():
        def ExpectComment(self, pos: int) -> typing.Tuple[bool, int, str]:
            _, pos, _ = self.ExpectWhitespace(pos)
            if self.data[pos:pos+2] == "/*":
                spos = pos
                while pos < len(self.data):
                    if self.data[pos:pos+2] == "*/": 
                        pos += 2
                        break
                    pos += 1
                return True, pos, self.data[spos:pos]
            return False, pos, ""

        def ExpectWhitespace(self, pos: int) -> typing.Tuple[bool, int, str]:
            spos = pos
            while pos < len(self.data):
                if self.data[pos:pos+4] == "\n...": # Skip over continue param symbol
                    pos += 4
                    continue
                if self.data[pos] not in [" ", "\t", "\n", "\r"]: break
                pos += 1
            return True, pos, self.data[spos:pos]

        def ExpectOptionalParam(self, pos:int) -> typing.Tuple[bool, int, str]: # Some param can be optional.
            while pos < len(self.data):
                if self.data[pos] == "\n":
                    if self.data[pos+1:pos+4] == "...": pos += 4; continue
                    else                              : return False, pos+1, "" # Next line doesn't has continue param symbol, treat as no optional parameter
                if self.data[pos] not in [" ", "\t", "\r"]:
                    return True, pos, "" # Found non whitespace character
                pos += 1
            return False, pos, "" # No optional param because EOF reached

        def ExpectEOF(self, pos: int) -> typing.Tuple[bool, int, str]:
            return pos >= len(self.data), pos, ""

        def ExpectString(self, pos: int) -> typing.Tuple[bool, int, str]: # REQ, https://x.y, 123.45, 
            """  
            Expect simple string. No new line between string. 

            Single space can be in string (double or more spaces are treated as separator)

            Example: https://127.0.0.1/ping, 12345, A string here, Template string: ${var}
            """
            _, pos, _ = self.ExpectWhitespace(pos)
            res = ""
            while pos < len(self.data):
                if self.data[pos] in ["\t", "\n", "\r"]: 
                    break # Separator whitespace
                if self.data[pos:pos+2] in ["  ", " \t", " \n", " \r"]: 
                    pos += 1
                    break # 2 whitespace = Seperate
                res += self.data[pos]
                pos += 1
            return True, pos, res

        def ExpectOp(self, pos: int) -> typing.Tuple[bool, int, str]: # TODO:
            _, pos, _ = self.ExpectWhitespace(pos)
            if self.data[pos:pos+1] == "+": # Add operator
                return True, pos+1, "+"

            return False, pos, None

        def ExpectExpr(self, pos: int) -> typing.Tuple[bool, int, typing.Any]: # 1, {"x": "json"}, YML{x: json}, asdf, 1 + 2, 1    +     2
            #print("Parsing Expr at: <%s>" % (self.data[pos:pos+20].encode()))
            _, pos, _ = self.ExpectWhitespace(pos)
            res = None
            def addRes(data): # FUTURE: Handle operation left right 
                nonlocal res
                res = data 
            if pos >= len(self.data): return False, pos, None
            if self.data[pos] == '{': # YAML
                pos += 1
                bracket = 0
                yamlData = ""
                while pos < len(self.data):
                    if self.data[pos] == '{': bracket += 1
                    if self.data[pos] == '}':
                        if bracket == 0: pos += 1; break
                        bracket -= 1
                    if self.data[pos] == '\\': pos += 1 # Escaping
                    yamlData += self.data[pos:pos+1]
                    pos += 1
                addRes(APT.Expr.Object(yaml.safe_load(yamlData)))
                self.pos = pos
            elif self.Peek(self.ExpectString): # String data as generic lit
                addRes(APT.Expr.StringLit(self.Scan(self.ExpectString)).deriveType())
                pos = self.pos

            if not self.Peek(self.ExpectOp): # No operation comes after this so the expression ends here
                return True, pos, res

            op = self.Scan(self.ExpectOp)
            if op in ["+"]: # If is in binary op
                ok, pos, rightExpr = self.ExpectExpr(self.pos)
                if not ok :
                    return False, pos, res
                res = APT.Expr.BinOp(op, res, rightExpr)
            return True, pos, res

        def Peek(self, expect) -> bool:
            ok, _, _ = expect(self.pos)
            return ok
        def Scan(self, expect):
            _, self.pos, val = expect(self.pos)
            return val

        def __init__(self, f: typing.TextIO):
            self.f = f
            self.data = f.read()
            self.pos = 0
            self.lastStatementPos = 0
            self.error = None
            self.eof = False

        def GetLastStatementLineNumber(self):
            return self.data.count("\n", 0, self.lastStatementPos)+1
        def Next(self):
            if self.Peek(self.ExpectEOF):
                self.eof = True
                return None
            if self.Peek(self.ExpectComment): # Read comment between statement
                self.Scan(self.ExpectComment) 
                return self.Next()
            
            val = self.Scan(self.ExpectString)
            self.lastStatementPos = self.pos
            if val == APT.Token.SECT : # SECT  [name]
                name = self.Scan(self.ExpectExpr)
                return APT.Statement.Section(name)
            if val == APT.Token.REQ: # REQ  [method]  [url]  [data?]
                method = self.Scan(self.ExpectExpr)
                url = self.Scan(self.ExpectExpr)
                data = self.Scan(self.ExpectExpr) if self.Peek(self.ExpectOptionalParam) else None
                return APT.Statement.Request(method, url, data)
            if val == APT.Token.RES: # RES  [data?]
                data = self.Scan(self.ExpectExpr)
                return APT.Statement.Response(data)
            if val == APT.Token.SET: # SET  [varname]  [data]
                varname = self.Scan(self.ExpectString)
                data = self.Scan(self.ExpectExpr)
                return APT.Statement.Set(varname, data)
            else: return "UNKNOWN STATEMENT: "+val


    # AMC class
    def __init__(self, f: typing.TextIO):
        self.f = f
        self.scanner = self.Scanner(f)

    def Next(self):
        return self.scanner.Next()


# APT Runner
class APTRunner():
    def __init__(self, f: typing.TextIO):
        self.APT = APT(f)
        self.lastRes = None
        self.testFailed = False
        self.env = APTEnv()

    def Fail(self, msg):
        self.testFailed = True
        print("    [FAILED] at line %d: %s" % (self.APT.scanner.GetLastStatementLineNumber(), msg))

    def Run(self):
        while self.APT.scanner.error == None and not self.APT.scanner.eof:
            stmt = self.APT.Next()

            if isinstance(stmt, APT.Statement.Section): # Section
                stmt:APT.Statement.Section
                print(stmt.name.resolve(self.env))

            if isinstance(stmt, APT.Statement.Request): # Request
                stmt:APT.Statement.Request
                method = stmt.method.resolve(self.env)
                url = stmt.url.resolve(self.env)
                try :
                    if stmt.data == None:
                        self.lastRes = requests.request(method, url)
                    else:
                        data = stmt.data.resolve(self.env)
                        print("    Requesting", data)
                        self.lastRes = requests.request(method, url, data=json.dumps(data))
                except Exception as e:
                    self.Fail("Request error: %s" % e)

            if isinstance(stmt, APT.Statement.Response):
                stmt:APT.Statement.Response
                data = stmt.data.resolve(self.env)
                if data == None:
                    self.Fail("Expecting 'None' is not allowed")
                    return
                print("    Expecting", data)

                res = {
                    "$status": None,
                    "$header": {}
                }
                try: 
                    if self.lastRes != None:
                        res["$status"] = self.lastRes.status_code
                        for k in self.lastRes.headers:
                            res["$header"][k] = self.lastRes.headers[k]
                        res["$body"] = self.lastRes.text
                        res.update(self.lastRes.json())
                except: pass

                def check(obj, expect, kPrefix):    
                    for k in expect:
                        actual = accessObj(obj,k)
                        if isinstance(expect[k], dict):
                            check(actual, expect[k], kPrefix + k + ".")
                        else:
                            if actual != expect[k]:
                                self.Fail("response not matched at [%s]. Expected=%s, Actual=%s" % (kPrefix + k, actual, expect[k]))

                if isinstance(data, dict):
                    check(res, data, "")
                else:
                    self.Fail("unknown response expectation: %s" %(data))

            if isinstance(stmt, APT.Statement.Set):
                stmt:APT.Statement.Set
                self.env.setVar(stmt.varname, stmt.data.resolve(self.env))
        if not self.testFailed:
            print("All test passed!")
        else:
            print("Test failed. See logs for error")

def run(filepath):
    _, ext = os.path.splitext(filepath)
    if ext != ".apitest":
        return
    print("\n\n%s" % filepath)
    print("===========================")
    with open(filepath, "r") as f:
        runner = APTRunner(f)
        runner.Run()

def main(argv):
    # python runner.py tests/

    # Loop in folders
    for target in argv[1:]:
        if os.path.isfile(target):
            run(target)
        for (dirpath, _, filenames) in os.walk(target):
            for f in filenames:
                run(os.path.join(dirpath, f))


if __name__ == "__main__":
    main(sys.argv)