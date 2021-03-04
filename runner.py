import sys, os, typing, enum, requests, json, yaml, re, random, time
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
    def __init__(self):             
        self.vars, self.at = ({}, None)
        self.specialVars = {
            "$_RANDOM": lambda : random.randint(0,999999999),
            "$_TIMESTAMP": lambda : int(time.time()),
            "$_UID": lambda : datetime.now().strftime("%Y%m%d%H%M%S") + str(random.randint(0,999999999))
        }
    def setVar(self, varname, val): self.vars[normalizeVarname(varname)] = val
    def setAtVar(self, val):        self.at = val
    def getAtVar(self):             return self.at
    def getVar(self, varname):      
        if normalizeVarname(varname) in self.specialVars:
            return self.specialVars[normalizeVarname(varname)]()
        return None if normalizeVarname(varname) not in self.vars else self.vars[normalizeVarname(varname)]

class APT() :
    class Token():
        REQ = "REQ"
        SECT = "SECT"
        RES = "RES"
        SET = "SET"
        PREREQ = "PREREQ" # PRE Requisite
        ASSERT = "ASSERT"
        PRINT = "PRINT"

    class Expr():
        class Base():
            def __init__(self, val):    self.val = val
            def __str__(self):          return str(self.val)
            def resolve(self, env):     return self.val
        class Null(Base): pass
        class Object(Base): 
            def resolve(self, env):
                def do(data): # Copy and resolve
                    nonlocal env
                    if isinstance(data, dict):
                        o = {}
                        for k in data:
                            o[k] = do(data[k])
                        return o
                    elif isinstance(data, list):
                        l = []
                        for d in data:
                            l.append(do(d))
                        return l
                    elif isinstance(data, str):
                        return APT.Expr.StringLit(data).resolve(env)
                    return data
                return do(self.val)
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
                    print("File not exists:" + fname)
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
                if self.op == "+": # TODO: Move to env
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
        class Prereq():
            def __init__(self, filename:str):                               self.filename = filename
            def __str__(self):                                              return "PREREQ <%s>" % (self.filename)
        class Assert():
            def __init__(self, data:'APT.Expr.Base', a:'APT.Expr.Base'):    self.data, self.assertion = data, a
            def __str__(self):                                              return "ASSERT <%s> <%s>" % (self.data, self.assertion)
        class Print():
            def __init__(self, data:'APT.Expr.Base'):                       self.data = data
            def __str__(self):                                              return "PRINT <%s> <%s>" % (self.data)
    
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

        def ExpectNonCode(self, pos: int) -> typing.Tuple[bool, int, str]:
            """ Expect whitespace or comment part until reach next code"""
            while pos < len(self.data):
                spos = pos
                _, pos, _ = self.ExpectComment(pos)
                _, pos, _ = self.ExpectWhitespace(pos)
                if pos == spos: break
            return True, pos, ""

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
            _, pos, _ = self.ExpectNonCode(pos)
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
            _, pos, _ = self.ExpectNonCode(pos)
            if self.data[pos:pos+1] == "+": # Add operator
                return True, pos+1, "+"

            return False, pos, None

        def ScanExpr(self, pos: int) -> typing.Tuple[bool, int, typing.Any]: # 1, {"x": "json"}, YML{x: json}, asdf, 1 + 2, 1    +     2
            _, pos, _ = self.ExpectNonCode(pos)
            res = None 
            if pos >= len(self.data): return False, pos, None
            if self.data[pos] == '{': # Object lit
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
                res = APT.Expr.Object(yaml.safe_load(yamlData))
                self.pos = pos
            elif self.Peek(self.ExpectString): # String data as generic lit
                res = APT.Expr.StringLit(self.Scan(self.ExpectString)).deriveType()
                pos = self.pos
                
            if not self.Peek(self.ExpectOp): # No operation comes after this so the expression ends here
                return True, pos, res

            op = self.Scan(self.ExpectOp)
            if op in ["+"]: # If is in binary op
                ok, pos, rightExpr = self.ScanExpr(self.pos)
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
                name = self.Scan(self.ScanExpr)
                return APT.Statement.Section(name)
            if val == APT.Token.REQ: # REQ  [method]  [url]  [data?]
                method = self.Scan(self.ScanExpr)
                url = self.Scan(self.ScanExpr)
                data = self.Scan(self.ScanExpr) if self.Peek(self.ExpectOptionalParam) else None
                return APT.Statement.Request(method, url, data)
            if val == APT.Token.RES: # RES  [data?]
                data = self.Scan(self.ScanExpr)
                return APT.Statement.Response(data)
            if val == APT.Token.SET: # SET  [varname]  [data]
                varname = self.Scan(self.ExpectString)
                data = self.Scan(self.ScanExpr)
                return APT.Statement.Set(varname, data)
            if val == APT.Token.PREREQ: # PREREQ  [filename]
                filename = self.Scan(self.ExpectString)
                return APT.Statement.Prereq(filename)
            if val == APT.Token.ASSERT: # ASSERT  [data]  [assertion]
                data = self.Scan(self.ScanExpr)
                assertion = self.Scan(self.ScanExpr)
                return APT.Statement.Assert(data, assertion)
            if val == APT.Token.PRINT: # PRINT  [data]
                data = self.Scan(self.ScanExpr)
                return APT.Statement.Print(data)
            else: return "UNKNOWN STATEMENT: "+val


    # AMC class
    def __init__(self, f: typing.TextIO):
        self.f = f
        self.scanner = self.Scanner(f)

    def Next(self):
        return self.scanner.Next()


# APT Runner
class APTRunner():
    def __init__(self, f: typing.TextIO, isSubtest = False, env = None):
        self.APT = APT(f)
        self.lastRes = None
        self.testFailed = False
        self.isSubtest = isSubtest
        self.env = APTEnv() if env == None else env
    def Fail(self, msg):
        self.testFailed = True
        print("    [FAILED] at line %d: %s" % (self.APT.scanner.GetLastStatementLineNumber(), msg))
    def DoAssert(self, data, assertion):
        def check(obj, expect, kPrefix):    
            for k in expect:
                actual = accessObj(obj,k)
                if isinstance(expect[k], dict):
                    check(actual, expect[k], kPrefix + k + ".")
                else:
                    if actual != expect[k]:
                        self.Fail("response not matched at [%s]. Expected=%s, Actual=%s" % (kPrefix + k, expect[k], actual))
        if isinstance(assertion, dict):
            check(data, assertion, "")
        else:
            if data != assertion:
                self.Fail("Assertion failed. Expected=%s, Actual=%s" % (assertion, data))
            
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
                        self.lastRes = requests.request(method, url, verify=False)
                    else:
                        data = stmt.data.resolve(self.env)
                        print("    Requesting", data)
                        headers = {}
                        if "$header" in data:
                            for k in data["$header"]:
                                headers[k] = str(data["$header"][k])
                            del data["$header"]
                        self.lastRes = requests.request(method, url, data=json.dumps(data), headers=headers, timeout=1, verify=False)
                except Exception as e:
                    self.Fail("Request error: %s" % e)

            if isinstance(stmt, APT.Statement.Response): # Response
                stmt:APT.Statement.Response
                expect = stmt.data.resolve(self.env)
                if expect == None:
                    self.Fail("Expecting 'None' is not allowed")
                    return
                print("    Expecting", expect)

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

                # Extract var with {$set: ["field.field -> $aaa"]}
                if "$set" in expect:
                    for setcmd in expect["$set"]:
                        field, var = setcmd.split("->")
                        self.env.setVar(var.strip(), accessObj(res, field.strip()))
                    del expect["$set"]
                    
                self.DoAssert(res, expect)

            if isinstance(stmt, APT.Statement.Set): # Set
                stmt:APT.Statement.Set
                self.env.setVar(stmt.varname, stmt.data.resolve(self.env))
            if isinstance(stmt, APT.Statement.Prereq): # Prerequisite
                stmt:APT.Statement.Prereq
                with open(stmt.filename, "r") as f:
                    subrunner = APTRunner(f, True, self.env)
                    subrunner.Run()
                    if subrunner.testFailed:
                        self.Fail("Prerequisite failed")

            if isinstance(stmt, APT.Statement.Assert): # Assert
                stmt:APT.Statement.Assert
                data = stmt.data.resolve(self.env)
                assertion = stmt.assertion.resolve(self.env)
                self.DoAssert(data, assertion)

            if isinstance(stmt, APT.Statement.Print): # Print
                stmt:APT.Statement.Print
                data = stmt.data.resolve(self.env)
                print("    [PRINT] at line %d: %s" % (self.APT.scanner.GetLastStatementLineNumber(), str(data)))

        if not self.isSubtest:
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