from vyper.exceptions import (
    ConstancyViolationException
)
from vyper.parser.lll_node import (
    LLLnode
)
from vyper.parser.parser_utils import (
    pack_arguments,
    getpos
)
from vyper.signatures.function_signature import (
    FunctionSignature
)
from vyper.types import (
    BaseType,
    ByteArrayType,
    TupleType,
    ceil32,
    get_size_of_type,
)


def call_lookup_specs(stmt_expr, context):
    from vyper.parser.expr import Expr
    method_name = stmt_expr.func.attr
    expr_args = [Expr(arg, context).lll_node for arg in stmt_expr.args]
    sig = FunctionSignature.lookup_sig(context.sigs, method_name, expr_args, stmt_expr, context)
    return method_name, expr_args, sig


def make_call(stmt_expr, context):
    _, _, sig = call_lookup_specs(stmt_expr, context)
    if sig.private:
        return call_self_private(stmt_expr, context, sig)
    else:
        return call_self_public(stmt_expr, context, sig)


def call_make_placeholder(stmt_expr, context, sig):
    output_placeholder = context.new_placeholder(typ=sig.output_type)
    if isinstance(sig.output_type, BaseType):
        returner = output_placeholder
    elif isinstance(sig.output_type, ByteArrayType):
        returner = output_placeholder + 32
    elif isinstance(sig.output_type, TupleType):
        returner = output_placeholder
    return output_placeholder, returner


def call_self_private(stmt_expr, context, sig):
    # ** Private Call **
    # Steps:
    # (x) push current local variables
    # (x) push arguments
    # (x) push jumpdest (callback ptr)
    # (x) jump to label
    # (x) pop return values
    # (x) pop local variables

    method_name, expr_args, sig = call_lookup_specs(stmt_expr, context)
    pop_local_vars = []
    push_local_vars = []
    pop_return_values = []
    push_args = []

    if context.is_constant and not sig.const:
        raise ConstancyViolationException(
            "May not call non-constant function '%s' within a constant function." % (method_name),
            getpos(stmt_expr)
        )

    # Push local variables.
    if context.vars:
        var_slots = [(v.pos, v.size) for name, v in context.vars.items()]
        var_slots.sort(key=lambda x: x[0])
        mem_from, mem_to = var_slots[0][0], var_slots[-1][0] + var_slots[-1][1] * 32
        push_local_vars = [
            ['mload', pos] for pos in range(mem_from, mem_to, 32)
        ]
        pop_local_vars = [
            ['mstore', pos, 'pass'] for pos in reversed(range(mem_from, mem_to, 32))
        ]

    # Push Arguments
    if expr_args:
        inargs, inargsize, arg_pos = pack_arguments(sig, expr_args, context, return_placeholder=False, pos=getpos(stmt_expr))
        push_args += [inargs]
        push_args += [
            ['mload', pos] for pos in range(arg_pos, arg_pos + ceil32(inargsize - 4), 32)
        ]

    # Jump to function label.
    jump_to_func = [
        ['add', ['pc'], 6],
        ['goto', 'priv_{}'.format(sig.method_id)],
        ['jumpdest'],
    ]

    # Pop return values.
    returner = ['pass']
    if sig.output_type:
        output_size = get_size_of_type(sig.output_type) * 32
        output_placeholder, returner = call_make_placeholder(stmt_expr, context, sig)
        if output_size > 0:
            pop_return_values = [
                ['mstore', ['add', output_placeholder, pos], 'pass'] for pos in range(0, output_size, 32)
            ]

    o = LLLnode.from_list(
        ['seq_unchecked'] +
        push_local_vars + push_args +
        jump_to_func +
        pop_return_values + pop_local_vars + [returner],
        typ=sig.output_type, location='memory', pos=getpos(stmt_expr), annotation='Internal Call: %s' % method_name,
        add_gas_estimate=sig.gas
    )
    o.gas += sig.gas
    return o


def call_self_public(stmt_expr, context, sig):
    # self.* style call to a public function.
    method_name, expr_args, sig = call_lookup_specs(stmt_expr, context)
    if context.is_constant and not sig.const:
        raise ConstancyViolationException(
            "May not call non-constant function '%s' within a constant function." % (method_name),
            getpos(stmt_expr)
        )
    add_gas = sig.gas  # gas of call
    inargs, inargsize, _ = pack_arguments(sig, expr_args, context, pos=getpos(stmt_expr))
    output_placeholder = context.new_placeholder(typ=sig.output_type)
    multi_arg = []
    output_placeholder, returner = call_make_placeholder(stmt_expr, context, sig)
    o = LLLnode.from_list(
        multi_arg +
        ['seq',
            ['assert',
                ['call',
                    ['gas'], ['address'], 0, inargs, inargsize, output_placeholder, get_size_of_type(sig.output_type) * 32]], returner],
        typ=sig.output_type, location='memory',
        pos=getpos(stmt_expr), add_gas_estimate=add_gas, annotation='Internal Call: %s' % method_name
    )
    o.gas += sig.gas
    return o