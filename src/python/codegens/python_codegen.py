import codegen
from mixins.restricted_multiply import RestrictedMultiply
from qcml.codes.function import PythonFunction
from qcml.codes.coefficients import OnesCoeff, ConstantCoeff
import qcml.codes.encoders as encoder

def wrap_self(f):
    def wrapped_code(self, *args, **kwargs):
        return f(*args, **kwargs)
    return wrapped_code

class PythonCodegen(codegen.Codegen):
    def __init__(self, dims):
        super(PythonCodegen, self).__init__(dims)
        self.__prob2socp = PythonFunction("prob_to_socp")
        self.__socp2prob = PythonFunction("socp_to_prob")

    @property
    def prob2socp(self):
        return self.__prob2socp

    @property
    def socp2prob(self):
        return self.__socp2prob

    # function to get cone sizes
    def python_cone_sizes(self):
        yield "p, m, n = %d, %d, %d" % (self.num_lineqs, self.num_conic + self.num_lps, self.num_vars)

    # function to get cone dimensions
    def python_dimensions(self):
        def cone_tuple_to_str(x):
            num, sz = x
            if num == 1: return "[%s]" % sz
            else: return "%s*[%s]" % (num, sz)
        cone_list_str = '[]'
        if self.cone_list:
            cone_list_str = map(cone_tuple_to_str, self.cone_list)
            cone_list_str = '+'.join(cone_list_str)

        yield "dims = {'l': %d, 'q': %s, 's': []}" % (self.num_lps, cone_list_str)

    def functions_setup(self, program_node):
        # add the arguments to the function
        self.prob2socp.add_arguments("params")
        self.socp2prob.add_arguments("x")

        # add some documentation
        self.prob2socp.document("maps 'params' into a dictionary of SOCP matrices")
        self.prob2socp.document("'params' ought to contain:")
        shapes = ("  '%s' has shape %s" % (v, v.shape.eval(self.dims)) for v in program_node.parameters.values())
        self.prob2socp.document(shapes)

        # now import cvxopt and itertools
        self.prob2socp.add_lines("import cvxopt as o")
        self.prob2socp.add_lines("import itertools")
        self.prob2socp.newline()
        self.prob2socp.add_comment("convert possible numpy parameters to cvxopt matrices")
        self.prob2socp.add_lines("from qcml.helpers import convert_to_cvxopt")
        self.prob2socp.add_lines("params = convert_to_cvxopt(params)")
        self.prob2socp.newline()

        # set up the data structures
        self.prob2socp.add_lines(self.python_cone_sizes())
        self.prob2socp.add_lines("c = o.matrix(0, (n,1), tc='d')")
        self.prob2socp.add_lines("h = o.matrix(0, (m,1), tc='d')")
        self.prob2socp.add_lines("b = o.matrix(0, (p,1), tc='d')")
        self.prob2socp.add_lines("Gi, Gj, Gv = [], [], []")
        self.prob2socp.add_lines("Ai, Aj, Av = [], [], []")
        self.prob2socp.add_lines(self.python_dimensions())

    def functions_return(self, program_node):
        self.prob2socp.add_comment("construct index and value lists for G and A")
        self.prob2socp.add_lines("Gi = list(itertools.chain.from_iterable(Gi))")
        self.prob2socp.add_lines("Gj = list(itertools.chain.from_iterable(Gj))")
        self.prob2socp.add_lines("Gv = list(itertools.chain.from_iterable(Gv))")
        self.prob2socp.add_lines("Ai = list(itertools.chain.from_iterable(Ai))")
        self.prob2socp.add_lines("Aj = list(itertools.chain.from_iterable(Aj))")
        self.prob2socp.add_lines("Av = list(itertools.chain.from_iterable(Av))")
        self.prob2socp.add_lines("G = o.spmatrix(Gv, Gi, Gj, (m,n), tc='d')")
        self.prob2socp.add_lines("A = o.spmatrix(Av, Ai, Aj, (p,n), tc='d')")
        self.prob2socp.add_lines("return {'c': c, 'G': G, 'h': h, 'A': A, 'b': b, 'dims': dims}")

        self.socp2prob.document("recovers the problem variables from the solver variable 'x'")
        # recover the old variables
        recover = (
            "'%s' : x[%s:%s]" % (k, self.varstart[k], self.varstart[k]+self.varlength[k])
                for k in program_node.variables.keys()
        )
        self.socp2prob.add_lines("return {%s}" % ', '.join(recover))

    def stuff_c(self, start, end, expr):
        yield "c[%s:%s] = %s" % (start, end, encoder.toPython(expr))

    def stuff_b(self, start, end, expr):
        yield "b[%s:%s] = %s" % (start, end, encoder.toPython(expr))

    def stuff_h(self, start, end, expr, stride = None):
        if stride is not None:
            yield "h[%s:%s:%s] = %s" % (start, end, stride, encoder.toPython(expr))
        else:
            yield "h[%s:%s] = %s" % (start, end, encoder.toPython(expr))

    def stuff_G(self, row_start, row_end, col_start, col_end, expr, row_stride = 1):
        n = (row_end - row_start)/row_stride
        if n > 1 and expr.isscalar:
            expr = OnesCoeff(n,ConstantCoeff(1))*expr
        to_sparse = expr.to_sparse()
        if to_sparse: yield encoder.toPython(to_sparse)
        yield "Gi.append(%s)" % encoder.toPython(expr.I(row_start, row_stride))
        yield "Gj.append(%s)" % encoder.toPython(expr.J(col_start))
        yield "Gv.append(%s)" % encoder.toPython(expr.V())

    def stuff_A(self, row_start, row_end, col_start, col_end, expr, row_stride = 1):
        n = (row_end - row_start)/row_stride
        if n > 1 and expr.isscalar:
            expr = OnesCoeff(n,ConstantCoeff(1))*expr
        to_sparse = expr.to_sparse()
        if to_sparse: yield encoder.toPython(to_sparse)
        yield "Ai.append(%s)" % encoder.toPython(expr.I(row_start, row_stride))
        yield "Aj.append(%s)" % encoder.toPython(expr.J(col_start))
        yield "Av.append(%s)" % encoder.toPython(expr.V())

