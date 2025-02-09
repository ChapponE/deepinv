import torch

from .optim_iterator import OptimIterator, fStep, gStep


class CPIteration(OptimIterator):
    r"""
    Single iteration of the Chambolle-Pock algorithm.

    Class for a single iteration of the `Chambolle-Pock <https://hal.science/hal-00490826/document>`_ Primal-Dual (PD)
    algorithm for minimising :math:`\lambda F(Kx) + G(x)` or :math:`\lambda F(x) + G(Kx)` for generic functions :math:`F` and :math:`G`.
    Our implementation corresponds to Algorithm 1 of `<https://hal.science/hal-00490826/document>`_.

    If the attribute `"g_first"` is set to False (by default), the iteration is given by

    .. math::
        \begin{equation*}
        \begin{aligned}
        u_{k+1} &= \operatorname{prox}_{\sigma (\lambda F)^*}(u_k + \sigma K z_k) \\
        x_{k+1} &= \operatorname{prox}_{\tau G}(x_k-\tau K^\top u_{k+1}) \\
        z_{k+1} &= x_{k+1} + \beta(x_{k+1}-x_k) \\
        \end{aligned}
        \end{equation*}

    where :math:`(\lambda F)^*` is the Fenchel-Legendre conjugate of :math:`\lambda F`, :math:`\beta>0` is a relaxation parameter, and :math:`\sigma` and :math:`\tau` are step-sizes that should
    satisfy :math:`\sigma \tau \|K\|^2 \leq 1`.

    If the attribute `"g_first"` is set to True, the functions :math:`F` and :math:`G` are inverted in the previous iteration.

    In particular, setting :math:`F = \distancename`, :math:`K = A` and :math:`G = \regname`, the above algorithms solves

    .. math::

        \begin{equation*}
        \underset{x}{\operatorname{min}} \,\, \lambda \distancename(Ax, y) + \regname(x)
        \end{equation*}


    with a splitting on :math:`\distancename`, with not differentiability assumption needed on :math:`\distancename`
    or :math:`\regname`, not any invertibility assumption on :math:`A`.
    """

    def __init__(self, **kwargs):
        super(CPIteration, self).__init__(**kwargs)
        self.g_step = gStepCP(**kwargs)
        self.f_step = fStepCP(**kwargs)

    def forward(self, X, cur_prior, cur_params, y, physics):
        r"""
        Single iteration of the Chambolle-Pock algorithm.

        :param dict X: Dictionary containing the current iterate and the estimated cost.
        :param deepinv.optim.prior cur_prior: Instance of the Prior class defining the current prior.
        :param dict cur_params: dictionary containing the current parameters of the model.
        :param torch.Tensor y: Input data.
        :param deepinv.physics physics: Instance of the physics modeling the data-fidelity term.
        :return: Dictionary `{"est": (x, ), "cost": F}` containing the updated current iterate and the estimated current cost.
        """
        x_prev, z_prev, u_prev = X["est"]
        K = lambda x: cur_params["K"](x) if "K" in cur_params.keys() else x
        K_adjoint = (
            lambda x: cur_params["K_adjoint"](x)
            if "K_adjoint" in cur_params.keys()
            else x
        )
        if self.g_first:
            u = self.g_step(u_prev, K(z_prev), cur_prior, cur_params)
            x = self.f_step(x_prev, K_adjoint(u), y, physics, cur_params)
        else:
            u = self.f_step(u_prev, K(z_prev), y, physics, cur_params)
            x = self.g_step(x_prev, K_adjoint(u), cur_prior, cur_params)
        z = x + self.beta * (x - x_prev)
        F = self.F_fn(x, cur_prior, cur_params, y, physics) if self.has_cost else None

        return {"est": (x, z, u), "cost": F}


class fStepCP(fStep):
    r"""
    Chambolle-Pock fStep module.
    """

    def __init__(self, **kwargs):
        super(fStepCP, self).__init__(**kwargs)

    def forward(self, x, w, y, physics, cur_params):
        r"""
        Single Chambolle-Pock iteration step on the data-fidelity term :math:`\lambda f`.

        :param torch.Tensor x: Current first variable :math:`x` if `"g_first"` and :math:`u` otherwise.
        :param torch.Tensor w: Current second variable :math:`A^\top u` if `"g_first"` and :math:`A z` otherwise.
        :param torch.Tensor y: Input data.
        :param dict cur_params: Dictionary containing the current fStep parameters (keys `"stepsize"` and `"lambda"`).
        """
        if self.g_first:
            p = x - cur_params["stepsize"] * w
            return self.data_fidelity.prox(
                p, y, physics, cur_params["stepsize"] * cur_params["lambda"]
            )
        else:
            p = x + cur_params["sigma"] * w
            return self.data_fidelity.prox_d_conjugate(
                p, y, cur_params["sigma"], lamb=cur_params["lambda"]
            )


class gStepCP(gStep):
    r"""
    Chambolle-Pock gStep module.
    """

    def __init__(self, **kwargs):
        super(gStepCP, self).__init__(**kwargs)

    def forward(self, x, w, cur_prior, cur_params):
        r"""
        Single Chambolle-Pock iteration step on the prior term :math:`g`.

        :param torch.Tensor x: Current first variable :math:`u` if `"g_first"` and :math:`x` otherwise.
        :param torch.Tensor w: Current second variable :math:`A z` if `"g_first"` and :math:`A^\top u` otherwise.
        :param deepinv.optim.prior cur_prior: Instance of the Prior class defining the current prior.
        :param dict cur_params: Dictionary containing the current gStep parameters (keys `"prox_g"`, `"stepsize"` and `"g_param"`).
        """
        if self.g_first:
            p = x + cur_params["sigma"] * w
            return cur_prior.prox_conjugate(
                p, cur_params["sigma"], cur_params["g_param"]
            )
        else:
            p = x - cur_params["stepsize"] * w
            return cur_prior.prox(p, cur_params["stepsize"], cur_params["g_param"])
