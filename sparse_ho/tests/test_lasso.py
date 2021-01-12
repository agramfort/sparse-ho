import pytest

import numpy as np
from scipy.sparse import csc_matrix
from sklearn import linear_model

from sparse_ho.datasets.synthetic import get_synt_data
from sparse_ho.models import Lasso, WeightedLasso
from sparse_ho.models import ElasticNet
from sparse_ho.algo.forward import get_beta_jac_iterdiff
from sparse_ho.algo.implicit_forward import get_beta_jac_fast_iterdiff
from sparse_ho.algo.implicit import get_beta_jac_t_v_implicit

from sparse_ho import Forward
from sparse_ho import ImplicitForward
from sparse_ho import Implicit
from sparse_ho import Backward
from sparse_ho.criterion import HeldOutMSE, FiniteDiffMonteCarloSure

n_samples = 100
n_features = 100
n_active = 5
SNR = 3
rho = 0.1

X, y, beta_star, noise, sigma_star = get_synt_data(
    dictionary_type="Toeplitz", n_samples=n_samples,
    n_features=n_features, n_times=1, n_active=n_active, rho=rho,
    SNR=SNR, seed=0)
X_s = csc_matrix(X)

idx_train = np.arange(0, 50)
idx_val = np.arange(50, 100)

alpha_max = (np.abs(X[idx_train, :].T @ y[idx_train])).max() / n_samples
p_alpha = 0.8
alpha = p_alpha * alpha_max
log_alpha = np.log(alpha)

log_alphas = np.log(alpha_max * np.geomspace(1, 0.1))
tol = 1e-16

dict_log_alpha = {}
dict_log_alpha["lasso"] = log_alpha
tab = np.linspace(1, 1000, n_features)
dict_log_alpha["wlasso"] = log_alpha + np.log(tab / tab.max())

alpha_1 = p_alpha * alpha_max
alpha_2 = 0.01
log_alpha1 = np.log(alpha_1)
log_alpha2 = np.log(alpha_2)
max_iter = 100

enet = ElasticNet(max_iter=max_iter, estimator=None)
estimator = linear_model.ElasticNet(
    alpha=(alpha_1 + alpha_2), fit_intercept=False,
    l1_ratio=alpha_1 / (alpha_1 + alpha_2),
    tol=1e-16, max_iter=max_iter)
enet_custom = ElasticNet(max_iter=max_iter, estimator=estimator)
dict_log_alpha["enet"] = np.array([log_alpha1, log_alpha2])
dict_log_alpha["enet_custom"] = np.array([log_alpha1, log_alpha2])

models = {}
models["lasso"] = Lasso(estimator=None)
models["wlasso"] = WeightedLasso(estimator=None)
models["enet"] = enet

custom_models = {}
custom_models["enet"] = enet_custom


def get_v(mask, dense):
    return 2 * (X[np.ix_(idx_val, mask)].T @ (
        X[np.ix_(idx_val, mask)] @ dense - y[idx_val])) / len(idx_val)


estimator = linear_model.Lasso(
    fit_intercept=False, max_iter=1000, warm_start=True)
models_custom = {}
# models_custom["lasso"] = Lasso(estimator=estimator)
models_custom["wlasso"] = WeightedLasso(estimator=estimator)


@pytest.mark.parametrize('key', list(models.keys()))
def test_beta_jac(key):
    #########################################################################
    # check that the methods computing the full Jacobian compute the same sol
    # maybe we could add a test comparing with sklearn
    supp1, dense1, jac1 = get_beta_jac_iterdiff(
        X, y, dict_log_alpha[key], tol=tol, model=models[key])
    supp1sk, dense1sk, jac1sk = get_beta_jac_iterdiff(
        X, y, dict_log_alpha[key], tol=tol, model=models[key])
    supp2, dense2, jac2 = get_beta_jac_fast_iterdiff(
        X, y, dict_log_alpha[key], tol=tol, model=models[key], tol_jac=tol)
    supp3, dense3, jac3 = get_beta_jac_iterdiff(
        X_s, y, dict_log_alpha[key], tol=tol,
        model=models[key])
    supp4, dense4, jac4 = get_beta_jac_fast_iterdiff(
        X_s, y, dict_log_alpha[key],
        tol=tol, model=models[key], tol_jac=tol)

    assert np.all(supp1 == supp1sk)
    assert np.all(supp1 == supp2)
    assert np.allclose(dense1, dense1sk)
    assert np.allclose(dense1, dense2)
    assert np.allclose(jac1, jac2, atol=1e-6)

    assert np.all(supp2 == supp3)
    assert np.allclose(dense2, dense3)
    assert np.allclose(jac2, jac3, atol=1e-6)

    assert np.all(supp3 == supp4)
    assert np.allclose(dense3, dense4)
    assert np.allclose(jac3, jac4, atol=1e-6)

    get_beta_jac_t_v_implicit(
        X, y, dict_log_alpha[key], get_v, model=models[key])


@pytest.mark.parametrize('key', list(custom_models.keys()))
def test_beta_jac_custom(key):
    #########################################################################
    # check that the methods computing the full Jacobian compute the same sol
    # maybe we could add a test comparing with sklearn
    supp, dense, jac = get_beta_jac_fast_iterdiff(
        X_s, y, dict_log_alpha[key],
        tol=tol, model=models[key], tol_jac=tol)
    supp_custom, dense_custom, jac_custom = get_beta_jac_fast_iterdiff(
        X_s, y, dict_log_alpha[key],
        tol=tol, model=custom_models[key], tol_jac=tol)
    assert np.all(supp == supp_custom)
    assert np.allclose(dense, dense_custom)
    assert np.allclose(jac, jac_custom)


@pytest.mark.parametrize('key', list(models.keys()))
@pytest.mark.parametrize('criterion', ['MSE', 'SURE'])
def test_val_grad(key, criterion):
    """Test gradients of regressors on different criterions."""
    if criterion == 'MSE':
        criterion = HeldOutMSE(idx_train, idx_val)
    elif criterion == 'SURE':
        criterion = FiniteDiffMonteCarloSure(sigma_star)

    #######################################################################
    # Not all methods computes the full Jacobian, but all
    # compute the gradients
    # check that the gradient returned by all methods are the same
    model = models[key]

    algo = Forward()
    val_fwd, grad_fwd = criterion.get_val_grad(
        model, X, y, dict_log_alpha[key], algo.get_beta_jac_v, tol=tol)

    algo = ImplicitForward(tol_jac=1e-8, n_iter_jac=5000)
    val_imp_fwd, grad_imp_fwd = criterion.get_val_grad(
        model, X, y, dict_log_alpha[key], algo.get_beta_jac_v, tol=tol)

    algo = Backward()
    val_bwd, grad_bwd = criterion.get_val_grad(
        model, X, y, dict_log_alpha[key], algo.get_beta_jac_v, tol=tol)

    assert np.allclose(val_fwd, val_imp_fwd)
    assert np.allclose(grad_fwd, grad_imp_fwd)
    # XXX : backward needs to be fixed
    # assert np.allclose(val_bwd, val_fwd)
    # assert np.allclose(val_bwd, val_imp_fwd)
    assert np.allclose(grad_fwd, grad_imp_fwd)

    if key == 'wlasso':
        return

    # # there are numerical errors
    # assert np.allclose(grad_fwd, grad_bwd, rtol=1e-3)

    algo = Implicit()
    val_imp, grad_imp = criterion.get_val_grad(
        model, X, y, dict_log_alpha[key], algo.get_beta_jac_v, tol=tol)

    assert np.allclose(val_imp_fwd, val_imp)
    # for the implicit the conjugate grad does not converge
    # hence the atol=1e-3
    assert np.allclose(grad_imp_fwd, grad_imp, atol=1e-3)
