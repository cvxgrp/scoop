from . qc_parser import QCParser
from . codegens import PythonCodegen, \
    MatlabCodegen, \
    C_Codegen
from . helpers import profile, default_locals
from . errors import QC_DCPError
from . ast.expressions import Variable
from . ast import NodeVisitor

PARSE, CANONICALIZE, CODEGEN, COMPLETE = range(4)

SUPPORTED_LANGUAGES = {
    "C": C_Codegen,
    "python": PythonCodegen,
    "matlab": MatlabCodegen
}

# TODO: add custom Exception classes
# TODO: add test cases for ensuring that errors are properly triggered in
# all cases

class QCML(object):
    def __init__(self, debug = False):
        self.debug = debug
        self.state = PARSE

        self.program = None
        self.__codegen = None

        # keep track of the codegen language
        self.language = ""

    @property
    def prob2socp(self):
        return self.__codegen.prob2socp

    @property
    def socp2prob(self):
        return self.__codegen.socp2prob

    @profile
    def parse(self, text):
        """ Parse state enum.

            The parser moves from the EMPTY to the PARSED to the CANONICALIZED to
            the CODEGEN state.
        """
        self.program = QCParser().parse(text)
        if self.debug:
            self.program.show()

        if not self.program.is_dcp:
            # TODO: if debug, walk the tree and find the problem
            raise QC_DCPError("QCML parse: The problem is not DCP compliant.")
        self.state = CANONICALIZE

    @profile
    def canonicalize(self):
        if self.state > CANONICALIZE: return
        if self.state is PARSE:
            raise Exception("QCML canonicalize: No problem currently parsed.")

        self.program.canonicalize()
        if self.debug:
            print self.program
        self.state = CODEGEN

    @property
    def dims(self):
        return self.program.dimensions

    @dims.setter
    def dims(self, dims):
        if self.state is PARSE:
            raise Exception("QCML set_dims: No problem currently parsed.")

        self.program.dimensions = dims

        if self.state is COMPLETE:
            self.state = CODEGEN

    @profile
    def codegen(self, language="python", *args, **kwargs):
        if self.state is COMPLETE:
            self.state = CODEGEN
        if self.state is PARSE:
            raise Exception("QCML codegen: No problem currently parsed.")
        if self.state is CANONICALIZE:
            raise Exception("QCML codegen: No problem currently canonicalized.")

        try:
            codegen_class = SUPPORTED_LANGUAGES[language]
        except KeyError:
            raise Exception("QCML codegen: Invalid code generator. Must be one of: ", SUPPORTED_LANGUAGES.keys())
        else:
            self.__codegen = codegen_class(*args, **kwargs)
            self.__codegen.visit(self.program)

        # generate the prob2socp and socp2prob functions
        self.__codegen.codegen()

        if self.debug and hasattr(self.prob2socp, 'numbered_source'):
            print self.prob2socp.numbered_source
            print
            print self.socp2prob.numbered_source
            print

        self.state = COMPLETE
        self.language = language    # set our language

    @property
    def solver(self):
        if self.language != "python":
            raise Exception("QCML solver: Cannot execute code generated in %s" % self.language)
        if self.state is not COMPLETE:
            raise Exception("QCML solver: No python code currently generated.")

        try:
            import ecos
        except ImportError:
            raise ImportError("QCML solver: To generate a solver, requires ecos.")

        def solve_func(params):
            data = self.prob2socp(params)
            sol = ecos.solve(**data)
            result = self.socp2prob(sol['x'])
            result['info'] = sol['info']

            # set the objective value
            multiplier = self.__codegen.objective_multiplier
            offset = self.__codegen.objective_offset
            result['objval'] = multiplier * sol['info']['pcost'] + offset
            return result
        return solve_func

    @default_locals
    def solve(self, params, dims = None):
        """
            .solve(locals())
            .solve(dims,params)

            Assumes all matrices and vectors are cvxopt matrices.
        """
        # TODO: what happens if we call solve after codegen(C)?
        if self.state is PARSE:
            raise Exception("QCML solve: No problem currently parsed.")

        try:
            # attempt to set the dims; if this fails, usually means someone
            # set the dims externally and just wants to solve with the params
            self.dims = dims if dims else params
        except:
            raise
            raise Exception("QCML solve: Perhaps you've already canonicalized and/or generated code. Call .solver instead.")
        self.canonicalize()
        self.codegen("python")

        return self.solver(params)

    def printsource(self):
        print '\n\n'.join(self.__codegen.source)

    def prettyprintsource(self):
        print '\n\n'.join(self.__codegen.numbered_source)
