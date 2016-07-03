# Copyright 2016 P4FPGA Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import logging
import astbsv as ast
import exceptions
from utils import CamelCase, camelCase
from collections import OrderedDict

logger = logging.getLogger(__name__)

class Control (object):
    """
        Control module maps to a pipeline
    """
    def __init__(self, name):
        self.name = name
        self.init_table = None
        self.tables = OrderedDict()
        self.conditionals = OrderedDict()
        self.basic_blocks = []
        self.registers = []
        self.entry = []

    def buildFFs(self):
        TMP1 = "FIFOF#(MetadataRequest) default_req_ff <- mkFIFOF;"
        TMP2 = "FIFOF#(MetadataResponse) default_rsp_ff <- mkFIFOF;"
        TMP3 = "FIFOF#(MetadataRequest) %(name)s_req_ff <- mkFIFOF;"
        TMP4 = "FIFOF#(MetadataResponse) %(name)s_rsp_ff <- mkFIFOF;"
        TMP5 = "FIFOF#(MetadataRequest) currPacketFifo <- mkFIFOF;"
        stmt = []
        stmt.append(ast.Template(TMP1))
        stmt.append(ast.Template(TMP2))
        for t in self.tables.values():
            stmt.append(ast.Template(TMP3, {"name": t.name} ))
            stmt.append(ast.Template(TMP4, {"name": t.name} ))
        stmt.append(ast.Template(TMP5))
        return stmt

    def buildRegisterArrays(self):
        TMP1 = "RegisterIfc#(%(asz)s, %(dsz)s) %(name)s <- mkP4Register(%(client)s);"
        stmt = []
        for r in self.registers:
            dsz = r['bitwidth']
            asz = r['size']
            name = r['name']
            stmt.append(ast.Template(TMP1, {"asz": asz, "dsz": dsz, "name": name, "client": "nil"}))
        return stmt

    def buildBasicBlocks(self):
        TMP1 = "%(type)s %(name)s <- mk%(type)s();"
        stmt = []
        stmt.append(ast.Template("// Basic Blocks"))
        basic_block_set = dict() # to ensure unique name
        for b in self.basic_blocks:
            btype = CamelCase(b.name)
            bname = b.name
            if bname in basic_block_set:
                basic_block_set[bname] += 1
                name = b.name + "_%s" % (basic_block_set[b.name])
            else:
                basic_block_set[bname] = 0
                name = b.name + "_0"
            stmt.append(ast.Template(TMP1, {"type": btype, "name": name}))
        return stmt

    def buildBasicBlockConnection(self):
        TMP1 = "mkChan(mkFIFOF, mkFIFOF, %(tbl)s.next_control_state_%(id)s, %(bb)s.prev_control_state);"
        stmt = []
        basic_block_set = dict() # to ensure unique name
        for k, v in self.tables.items():
            for idx, action in enumerate(v.actions):
                if action in basic_block_set:
                    basic_block_set[action] += 1
                    name = action + "_%s" % (basic_block_set[action])
                else:
                    basic_block_set[action] = 0
                    name = action + "_0"
                stmt.append(ast.Template(TMP1, {"tbl": k, "id": idx, "bb": name}))
        return stmt

    def buildRegisterMakeChan(self):
        #mkChan(mkFIFOF, );
        pass

    def buildConnection(self):
        TMP1 = "Vector#(numClients, Server#(MetadataRequest, MetadataResponse)) mds = replicate(toServer(default_req_ff, default_rsp_ff));"
        TMP2 = "mkConnection(mds, mdc);"
        stmt = []
        stmt.append(ast.Template(TMP1))
        stmt.append(ast.Template(TMP2))
        return stmt

    def buildTableInstance(self):
        TMP1 = "%(tblType)s %(tblName)s <- mk%(tblType)s();"
        TMP2 = "mkConnection(toClient(%(tblName)s_req_ff, %(tblName)s_rsp_ff), %(tblName)s.prev_control_state_%(id)s);"
        stmt = []
        for t in self.tables.values():
            stmt.append(ast.Template(TMP1, {"tblType": CamelCase(t.name),
                                            "tblName": t.name}))
        for t in self.tables.values():
            stmt.append(ast.Template(TMP2, {"tblName": t.name,
                                            "id": 0}))
        return stmt

    def buildDefaultRuleStmt(self, tblName):
        TMP1 = "default_req_ff.deq;"
        TMP2 = "let _req = default_req_ff.first;"
        TMP3 = "let meta = _req.meta;"
        TMP4 = "let pkt = _req.pkt;"
        TMP5 = "MetadataRequest req = MetadataRequest {pkt: pkt, meta: meta};"
        TMP6 = "%(name)s_req_ff.enq(req);"
        stmt = []
        stmt.append(ast.Template(TMP1))
        stmt.append(ast.Template(TMP2))
        stmt.append(ast.Template(TMP3))
        stmt.append(ast.Template(TMP4))
        if tblName in self.tables:
            stmt.append(ast.Template(TMP5))
            stmt.append(ast.Template(TMP6, {"name": tblName}))
        elif tblName in self.conditionals:
            _stmt = []
            self.buildConditionalStmt(tblName, _stmt)
            stmt += _stmt
        else:
            stmt.append(ast.Template("MetadataRequest req = MetadataRequest {pkt: pkt, meta: meta};"))
            stmt.append(ast.Template("currPacketFifo.enq(req);"))
        return stmt

    def buildIfStmt(self, true=None, false=None):
        _if = ast.If()
        if true:
            _if.stmt += self.buildIfStmt(true, false)
        if false:
            _if.stmt += self.buildIfStmt(true, false)
        return _if

    def buildConditionalStmt(self, tblName, stmt, metadata=set()):
        TMP1 = "MetadataRequest req = MetadataRequest {pkt: pkt, meta: meta};"
        TMP2 = "%(name)s_req_ff.enq(req);"
        toCurrPacketFifo = False

        def search_conditional (name):
            for key, cond in self.conditionals.items():
                print key, cond
                if key == name:
                    return cond
            return None

        if tblName is None:
            stmt.append(ast.Template("MetadataRequest req = MetadataRequest {pkt: pkt, meta: meta};"))
            stmt.append(ast.Template("currPacketFifo.enq(req);"))

        if tblName in self.tables:
            next_tables = self.tables[tblName].next_tables
            for next_table in next_tables.values():
                if next_table in self.tables:
                    self.buildConditionalStmt(next_table, stmt, metadata)
                elif next_table in self.conditionals:
                    self.buildConditionalStmt(next_table, stmt, metadata)
                else:
                    if not toCurrPacketFifo:
                        stmt.append(ast.Template("MetadataRequest req = MetadataRequest {pkt: pkt, meta: meta};"))
                        stmt.append(ast.Template("currPacketFifo.enq(req);"))
                        toCurrPacketFifo = True

        if tblName in self.conditionals:
            cond = search_conditional(tblName)
            expr = cond['expression']
            true_next = cond['true_next']
            false_next = cond['false_next']
            _meta = cond['metadata']
            for m in _meta:
                if type(m) is list:
                    metadata.add(tuple(m))
                else:
                    metadata.add(m)
            if true_next in self.tables:
                _stmt = []
                _stmt.append(ast.Template(TMP1, {"name": CamelCase(true_next)}))
                _stmt.append(ast.Template(TMP2, {"name": true_next}))
                stmt.append(ast.If(expr, _stmt))
            if false_next in self.tables:
                _stmt = []
                _stmt.append(ast.Template(TMP1, {"name": CamelCase(false_next)}))
                _stmt.append(ast.Template(TMP2, {"name": false_next}))
                stmt.append(ast.Else(_stmt))

            if true_next in self.conditionals:
                _stmt = []
                self.buildConditionalStmt(true_next, _stmt, metadata)
                stmt.append(ast.If(expr, _stmt))
            if false_next in self.conditionals:
                _stmt = []
                self.buildConditionalStmt(false_next, _stmt, metadata)
                stmt.append(ast.Else(_stmt))
        #return stmt

    def buildTableRuleStmt(self, tblName):
        TMP1 = "%(tblName)s_rsp_ff.deq;"
        TMP2 = "let _req = %(tblName)s_rsp_ff.first;"
        TMP3 = "let meta = _req.meta;"
        TMP4 = "let pkt = _req.pkt;"
        TMP5 = "let %(name)s = fromMaybe(?, meta.%(name)s);"
        stmt = []
        stmt.append(ast.Template(TMP1, {"tblName": tblName}))
        stmt.append(ast.Template(TMP2, {"tblName": tblName}));
        stmt.append(ast.Template(TMP3));
        stmt.append(ast.Template(TMP4));
        _stmt = []
        metadata = set()
        self.buildConditionalStmt(tblName, _stmt, metadata)
        for m in metadata:
            if type(m) is tuple:
                stmt.append(ast.Template(TMP5, {"name": "$".join(m)}))
        #print 'yyy', metadata
        stmt += _stmt
        return stmt

    def buildRules(self):
        TMP1 = "%(name)s_req_ff.notEmpty"
        TMP2 = "%(name)s_rsp_ff.notEmpty"
        rules = []
        rname = "default_next_state"
        cond = TMP1 % ({"name": "default", "type": "Default"})
        stmt = self.buildDefaultRuleStmt(self.init_table)
        rule = ast.Rule(rname, cond, stmt)
        rules.append(rule)
        for t in self.tables.values():
            rname = t.name + "_next_state"
            cond = TMP2 % ({"name": t.name, "type": CamelCase(t.name)})
            stmt = self.buildTableRuleStmt(t.name)
            rule = ast.Rule(rname, cond, stmt)
            rules.append(rule)
        return rules

    def buildMethodDefs(self):
        pass

    def buildModuleStmt(self):
        stmt = []
        stmt += self.buildFFs()
        stmt += self.buildConnection()
        stmt += self.buildTableInstance()
        stmt += self.buildBasicBlocks()
        stmt += self.buildRegisterArrays()
        stmt += self.buildBasicBlockConnection()
        stmt += self.buildRules()
        stmt.append(ast.Template("interface eventPktSend = toPipeOut(currPacketFifo);"))
        return stmt

    def emitInterface(self, builder):
        iname = CamelCase(self.name)
        table_intf = ast.Interface(typedef=iname)
        intf0 = ast.Interface("eventPktSend", "PipeOut#(MetadataRequest)")
        table_intf.subinterfaces.append(intf0)
        table_intf.emitInterfaceDecl(builder)

    def emitModule(self, builder):
        mname = "mk{}".format(CamelCase(self.name))
        iname = CamelCase(self.name)
        params = []
        decls = ["Vector#(numClients, Client#(MetadataRequest, MetadataResponse)) mdc"]
        provisos = []
        stmt = self.buildModuleStmt()
        module = ast.Module(mname, params, iname, provisos, decls, stmt)
        module.emit(builder)

    def emit(self, builder):
        for t in sorted(self.tables.values()):
            t.emit(builder)
        builder.newline()
        builder.append("// ====== %s ======" % (self.name.upper()))
        builder.newline()
        builder.newline()
        self.emitInterface(builder)
        self.emitModule(builder)
