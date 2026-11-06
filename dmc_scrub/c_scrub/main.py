import numpy as np
import pandas as pd

from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.utils.validation import check_is_fitted
import inspect

import torch
from torch import nn
import torch.nn.functional as F
import torchsort

from scipy.stats import spearmanr


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
        
        # unconstrained parameters
        self.logit_p = nn.Parameter( torch.logit(torch.rand(S)) )
        
        
        ## initializatio scheme
        init_log_gamma = (torch.rand(N)) * (-per_gamma_weighted)
        self.log_gamma = nn.Parameter(init_log_gamma)
        
        init_X = torch.rand(S, N) - (10*init_log_gamma[None, :])
        init_X[X==0] = -torch.inf
        self.log_Gamma = nn.Parameter(init_X)
        

    @property
    def p(self):
        return torch.sigmoid(self.logit_p)

    @property
    def Gamma(self):
        return torch.softmax(self.log_Gamma, dim=-1)

    @property
    def gamma(self):
        return torch.softmax(self.log_gamma, dim=0)

    
    def log_likelihood(
                        self,
                        X,
                        mu,
                        corr_X,
                        rank_mu,
                        lambda1,
                        lambda2
                        ):
        
        
        p = self.p
        Gamma = self.Gamma
        gamma = self.gamma
        
        
        Gamma_gamma_mixture = X * torch.log( (p[:, None] * Gamma) + ((1-p[:, None])*gamma[None, :]))
        
        per_gamma_weighted = corr_X * gamma
        
        p_vs_mu_rank_corr = differentiable_spearmanr_precomputed_target_rank(p[None, :], rank_mu)
        
        return( Gamma_gamma_mixture.mean() + \
                lambda2 * p_vs_mu_rank_corr - \
                lambda1 * per_gamma_weighted.mean()
                )



def run_C_SCRuB_fit(X_numpy, 
                    mu_numpy, 
                    lambda1=1e3, 
                    lambda2=1e2, 
                    lr=0.05,
                    optimizer=torch.optim.Adam, 
                    patience=5, 
                    min_delta = 1e-3,
                    min_iter=500,
                    max_iter=10000, 
                    n_mod_iters=3
                    ):

    X = torch.Tensor( X_numpy )
    mu = torch.Tensor( mu_numpy )

    with torch.no_grad():
        X_norm = F.normalize(X, p=1, dim=1)
        X_norm_numpy = X_norm.numpy()
        
        ## use this at the end as a threshold to zero out numbers below this
        min_relabund_val = min(X_norm[X_norm>0].min() / 100, 1e-3)
        

        X_mu_corrs = torch.Tensor( np.array([ spearmanr( X_norm_numpy[:, i], mu_numpy)[0] \
                                         for i in range(X_norm_numpy.shape[1]) ]) )

        X_mu_corrs[torch.isnan(X_mu_corrs)] = 0

        ## can do actual sorting on this one since we won't need this component's gradient
        mu_rank = torch.Tensor(pd.Series(mu).rank().values)
        mu_rank = mu_rank - mu_rank.mean()
        mu_rank = ( mu_rank / mu_rank.norm() )[None, :]
    
    
    ## loop through testing models on multiple initializations
    best_loss = float("inf")
    for mod_iter in range(n_mod_iters):
    
        ## initialize model object, optimizer
        CS = NN_C_SCRuB(X, X_mu_corrs)
        optim = optimizer( CS.parameters(), lr=lr )
        
        def closure():
            optim.zero_grad()
            objective = CS.log_likelihood(X, 
                                          mu, 
                                          corr_X=X_mu_corrs, 
                                          rank_mu=mu_rank,
                                          lambda1=lambda1,
                                          lambda2=lambda2
                                          )
            loss = -objective
            loss.backward()
            return loss


        ## run the fitting, using patience counter
        prev_loss = float("inf")
        patience_counter = 0
        for itera in range(max_iter):
            loss = optim.step(closure)
            loss_val = loss.item()

            improvement = prev_loss - loss_val
            prev_loss = loss_val


            if improvement > min_delta:
                patience_counter = 0
            elif itera > min_iter:
                patience_counter += 1

            if patience_counter >= patience:
                ## early stopping criteria is met
                break
                
                
        if best_loss > loss_val:
            final_model = CS
            best_loss = loss_val
                        
    with torch.no_grad():
        ## zero out very small relabunds 
        Gamma_out = final_model.Gamma.detach()
        Gamma_out[Gamma_out<min_relabund_val]=0
        Gamma_out=F.normalize(Gamma_out, p=1, dim=1)
        
        gamma_out = final_model.gamma.detach()
        gamma_out[gamma_out<min_relabund_val]=0
        gamma_out=F.normalize(gamma_out, p=1, dim=0)
            
    return({'Gamma':Gamma_out.numpy(), 
            'gamma':gamma_out.numpy(), 
            'p':final_model.p.detach().numpy(), 
            'loss':loss_val})




class C_SCRuB(BaseEstimator, TransformerMixin):
    def __init__(self, 
                 lambda1=1e3, 
                 lambda2=1e2, 
                 lr=0.05,
                 optimizer=torch.optim.Adam, 
                 patience=5, 
                 min_delta = 1e-3,
                 min_iter=500,
                 max_iter=10000
                 ):
        
        ## store parameters
        params = locals().copy()
        params.pop("self")
        self.params_ = params
        
            
    def fit(self, X, mu):
        """
        Fit C-SCRuB .

        Parameters
        ----------
        X : array-like, shape (n_samples, n_features), count matrix
        mu : array-like, concentration measurements, 
                assumes that mu ~~ \frac{1}{contamination}

        Returns
        -------
        self
        """
        X = np.asarray(X)
        mu = np.asarray(mu)
        
        self.X_=X
        self.mu_=mu
        
        out = run_C_SCRuB_fit(X, mu, **self.params_)
        done = [self.__setattr__(a,b) for a,b in out.items()]

        return self

    def transform(self, X, mu):
        """
        Returns a decontaminated `X` using the C-SCRuB-fitted parameters and `mu`.
                in SCRuB notation, returns `Gamma`. 

        Parameters
        ----------
        X : array-like, shape (n_samples, n_features), count matrix
        mu : array-like, concentration measurements, 
                assumes that mu ~~ \frac{1}{contamination}
        """
        check_is_fitted(self, ["Gamma", "gamma", "p"])
        
        df_input=False
        if type(X)==pd.DataFrame:
            df_input=True
            cols=X.columns
            rows=X.index
        
        X = np.asarray(X)
        mu = np.asarray(mu)
        
        ## if inputs are what we fit on, just return the stored Gamma 
        ## if not the same, re-run the fit and then return Gamma
        if ( self.X_ is not None ) and (self.mu_ is not None):
            self.fit(X, mu)
            self.X_=X
            self.mu_=mu
        
        elif not ( ( X==self.X_ ).min() and (mu==self.mu_).min() ):
            self.fit(X, mu)
            self.X_=X
            self.mu_=mu

            
        if df_input:
            return(pd.DataFrame(self.Gamma, index=rows, columns=cols))
        
        return(self.Gamma)
    
    def fit_transform(self, X, mu):
        """
        Fit to X and mu, then transform them.
        """
        return self.fit(X, mu).transform(X, mu)


