
import torch
from torch import nn
import torch.nn.functional as F
import torchsort

from scipy.stats import spearmanr
import numpy as np
import pandas as pd

from ...C_SCRuB.c_scrub.main import C_SCRuB


def differentiable_spearmanr_precomputed_target_rank(pred, 
                                                     target_rank, 
                                                     **kw):
    ## adapted from https://github.com/teddykoker/torchsort
    
    ## the adjustment we made in this implementation is using a pre-computed `target_rank`
    ## we do this because the `target_ranks` never change in our model, 
    ##  and we do not need the gradients upstream of `target_rank`. 
    ## therefore, for our particular use case, this implementation is ~2x as efficient
    
    
    pred = torchsort.soft_rank(pred, **kw)
    pred = pred - pred.mean()
    pred = pred / pred.norm()
    return (pred * target_rank).sum()



class NN_C_SCRuB(nn.Module):

    def __init__(self, X, per_gamma_weighted):
        super().__init__()

        S,N = X.shape

        self.logit_p = nn.Parameter( torch.logit( torch.rand(S)) )
        
        self.logit_p = nn.Parameter( 
                                   torch.logit(
                                        ( F.normalize(X.double(), dim=1, p=1) @ torch.sigmoid( per_gamma_weighted.double() )) ) )
        
        
        ## initializatio scheme
        init_log_gamma = (torch.rand(N)) * 10*(-per_gamma_weighted)
        init_log_gamma[X.sum(dim=0)==0] = -torch.inf
        
        self.log_gamma = nn.Parameter(init_log_gamma)
        
 
    @property
    def p(self):
        return torch.sigmoid(self.logit_p)

#     @property
#     def Gamma(self):
#         return torch.softmax(self.log_Gamma, dim=-1)

    @property
    def gamma(self):
        return torch.softmax(self.log_gamma, dim=0)

    
    def log_likelihood( self,
                        X,
                        lambda1=1e3,
                        lambda2=1e2
                        ):
        
        p = self.p
#         Gamma = self.Gamma
        gamma = self.gamma
        
        corr_X = self.corr_X
        rank_mu = self.rank_mu
        
        gamma_mixture = 100000 * X * ((1-p[:, None])*gamma[None, :])
        
        per_gamma_weighted = corr_X * gamma
        
        p_vs_mu_rank_corr = differentiable_spearmanr_precomputed_target_rank(p[None, :], rank_mu)
        
        return( gamma_mixture.mean() + \
                lambda2 * p_vs_mu_rank_corr - \
                lambda1 * per_gamma_weighted.mean()
                )





def initiate_per_batch_C_SCRuB_Object(X, mu ):

    mu_numpy = mu.numpy()
    
    with torch.no_grad():
        X_norm = F.normalize(X, p=1, dim=1)
        X_norm_numpy = X_norm.numpy()

        X_mu_corrs = torch.Tensor( np.array([ spearmanr( X_norm_numpy[:, i], mu_numpy)[0] \
                                         for i in range(X_norm_numpy.shape[1]) ]) )
        
        X_mu_corrs[torch.isnan(X_mu_corrs)] = 0

        ## can do actual sorting on this one since we won't need this component's gradient
        mu_rank = torch.Tensor(pd.Series(mu).rank().values)
        mu_rank = mu_rank - mu_rank.mean()
        mu_rank = ( mu_rank / mu_rank.norm() )[None, :]
    
    
    # REMOVING THE 'TEST MULTIPLE MODEL INITS FOR THE DEBIAS INTEGRATION
    # COULD BE INTERESTING TO ADD THIS BACK IN, THOUGH
    
    ## loop through testing models on multiple initializations
#     best_loss = float("inf")
#     for mod_iter in range(n_mod_iters):

    ## initialize model object, optimizer
    CS = NN_C_SCRuB(X, X_mu_corrs)
    CS.rank_mu = mu_rank
    CS.corr_X=X_mu_corrs
    return(CS)


def fit_transform(X, mu, batch_codes):
    """Run C-SCRuB independently per batch and restore original row order."""
    X = np.asarray(X)
    mu = np.asarray(mu)
    batch_codes = np.asarray(batch_codes)

    if X.ndim != 2:
        raise ValueError("X must be a two-dimensional sample-by-feature matrix.")
    if mu.ndim != 1 or mu.shape[0] != X.shape[0]:
        raise ValueError("mu must be one-dimensional with one value per sample.")
    if batch_codes.ndim != 1 or batch_codes.shape[0] != X.shape[0]:
        raise ValueError(
            "batch_codes must be one-dimensional with one value per sample."
        )

    transformed = np.empty(X.shape, dtype=float)
    for batch_code in pd.unique(batch_codes):
        in_batch = batch_codes == batch_code
        if int(in_batch.sum()) < 2:
            raise ValueError(
                f"Batch {batch_code!r} needs at least two samples for C-SCRuB."
            )
        batch_mu = mu[in_batch]
        if np.unique(batch_mu).size < 2:
            raise ValueError(
                f"Batch {batch_code!r} needs at least two concentration values."
            )
        transformed[in_batch] = C_SCRuB().fit_transform(
            X[in_batch],
            batch_mu,
        )
    return transformed
