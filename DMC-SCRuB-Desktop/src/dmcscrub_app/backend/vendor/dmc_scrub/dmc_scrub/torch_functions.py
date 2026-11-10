import warnings
warnings.filterwarnings("ignore",
                        ".*Consider increasing the value of the `num_workers` argument*")
warnings.filterwarnings("ignore", '.*In the future*')

import logging
logging.getLogger("pytorch_lightning").setLevel(logging.FATAL)


import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, LinearRegression

import pytorch_lightning as pl
import torch
from pytorch_lightning import LightningModule, Trainer, seed_everything, LightningDataModule
from torch import Tensor, nn
from torch.nn import functional as F
from torch.nn.functional import softmax, pairwise_distance
from torch.optim import Adam
from torch.optim.optimizer import Optimizer
from torchmetrics.functional import accuracy


from .data_loading import SklearnDataModule


from argparse import ArgumentParser
from typing import Any, Dict, List, Tuple, Type
from pytorch_lightning.callbacks.early_stopping import EarlyStopping


def rescale(xx):
    return(xx/xx.sum(axis=1)[:, np.newaxis] )

def to_categorical(y, num_classes):
    """ 1-hot encodes a tensor """
    return np.eye(num_classes, dtype='uint8')[y]




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
        
        self.logit_p = nn.Parameter( torch.logit( torch.rand(S)) )
        
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
    def gamma(self):
        return torch.softmax(self.log_gamma, dim=0)

    
    def log_likelihood(self,
                       lambda1=1e3,
                       lambda2=1e2
                       ):
        
        p = self.p
        gamma = self.gamma
        
        corr_X = self.corr_X
        rank_mu = self.rank_mu
        
        per_gamma_weighted = corr_X * gamma
        
        p_vs_mu_rank_corr = differentiable_spearmanr_precomputed_target_rank(p[None, :], rank_mu)
        
        return( 
                lambda2 * p_vs_mu_rank_corr - \
                lambda1 * per_gamma_weighted.mean()
                )


def initiate_per_batch_C_SCRuB_Object(X, mu):

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
        
    
    ## initialize model object, optimizer
    CS = NN_C_SCRuB(X, X_mu_corrs)
    
    CS.rank_mu = mu_rank
    CS.corr_X=X_mu_corrs
    
    return(CS)






class PL_C_SCRuB_DEBIASM(pl.LightningModule):
    """Logistic regression model."""

    def __init__(
        self,
        X, 
        mu,
        indices,
        batch_sim_strength: float,
        input_dim: int,
        num_classes: int,
        bias: bool = True,
        learning_rate: float = 1e-4,
        optimizer: Type[Optimizer] = Adam,
        l1_strength: float = 0.0,
        l2_strength: float = 0.0,
        w_l2 : float = 0.0,
        use_log: bool=False,
        prediction_loss=F.cross_entropy,
        **kwargs: Any,
    ) -> None:
        """
        Args:
            input_dim: number of dimensions of the input (at least 1)
            num_classes: number of class labels (binary: 2, multi-class: >2)
            bias: specifies if a constant or intercept should be fitted (equivalent to fit_intercept in sklearn)
            learning_rate: learning_rate for the optimizer
            optimizer: the optimizer to use (default: ``Adam``)
            l1_strength: L1 regularization strength (default: ``0.0``)
            l2_strength: L2 regularization strength (default: ``0.0``)
        """
        super().__init__()
        self.save_hyperparameters()
        self.optimizer = optimizer
        
#         1+'b'
        
        self.linear = nn.Linear(in_features=self.hparams.input_dim, 
                                out_features=self.hparams.num_classes, 
                                bias=bias)

        self.X=X[:, 1:]
        self.bs=X[:, 0].long()
        self.unique_bs=self.bs.unique().long()
        self.indices=indices ## used to map batches to C-SCRuB Gammas
        
        
        self.n_batches=self.unique_bs.max()+1
        self.batch_weights = torch.nn.Parameter(data = torch.zeros(self.n_batches,
                                                                   input_dim))

        self.batch_sim_str=batch_sim_strength
        self.prediction_loss=prediction_loss
        
        
        self.C_SCRuB_Layers = nn.ModuleDict()
        for batch in self.unique_bs:
            inds = self.bs==batch
            
            
            self.C_SCRuB_Layers[str(batch)] = initiate_per_batch_C_SCRuB_Object(self.X[inds], 
                                                                                mu[inds]
                                                                                )
            
            self.C_SCRuB_Layers[str(batch)].overall_dataset_inds = self.indices[inds]
        
    def forward(self, x: Tensor, p: Tensor) -> Tensor:
        
        batch_inds, x = x[:, 0], x[:, 1:]
        
        x = F.normalize( torch.pow(2, self.batch_weights[batch_inds.long()] ) * x, p=1 )

        
        x -= ( torch.cat([ self.C_SCRuB_Layers[str(batch)].gamma.unsqueeze(0)
                                                for batch in batch_inds.long() ], 
                                    dim=0 ) * ( 1 - p ) )

        x = F.normalize( F.relu(x), p=1 )
        
        x = self.linear(x)
        y_hat = softmax(x, dim=1)
        
        return y_hat
    
    
    def training_step(self, batch: Tuple[Tensor, Tensor], batch_idx: int) -> Dict[str, Tensor]:
        
        p = torch.cat([ self.C_SCRuB_Layers[str(batch)].p for batch in self.unique_bs]).unsqueeze(-1)\
                        [torch.cat([ self.C_SCRuB_Layers[str(batch)].overall_dataset_inds for batch in self.unique_bs ] )]
        
        
        x, y, indices = batch
        
        # flatten any input
        x = x.view(x.size(0), -1)

        y_hat = self.forward(x, p[indices])
        
        
        # PyTorch cross_entropy function combines log_softmax and nll_loss in single function
        loss = self.prediction_loss(y_hat, y, reduction="sum")
        
        # L1 regularizer
        if self.hparams.l1_strength > 0:
            l1_reg = self.linear.weight.abs().sum()
            loss += self.hparams.l1_strength * l1_reg

        # L2 regularizer
        if self.hparams.l2_strength > 0:
            l2_reg = self.linear.weight.pow(2).sum()
            loss += self.hparams.l2_strength * l2_reg
            
        # L2 regularizer
        if self.hparams.l2_strength > 0:
            l2_reg = self.linear.weight.pow(2).sum()
            loss += self.hparams.l2_strength * l2_reg
            
        # DOMAIN similarity regularizer / bias correction
        if self.batch_sim_str > 0:
    
    
            x1 = torch.stack( 
                              [ 
                                 ( 
                                    F.normalize(
                                       F.relu(
                                        F.normalize(
                                            torch.pow(2, self.batch_weights\
                                                    )[ torch.where(self.unique_bs==a)[0] ] * \
                                              (self.X[ torch.where(self.bs==a)[0] ] ) , 
                                                        p=1)\
                                       - ( ( 1 - p )[torch.where(self.bs==a)[0]] *\
                                                self.C_SCRuB_Layers[str(a)].gamma.unsqueeze(0) )
                                    ),
                                        p=1)
                                 ).mean(axis=0) for a in self.unique_bs 
                              ] 
                            )

            
            loss += sum( [pairwise_distance(x1, a) for a in x1] ).sum() *\
                                    self.batch_sim_str
            
        # L2 regularizer for bias weight    
        if self.hparams.w_l2 > 0:
            # L2 regularizer for weighting parameter
            l2_reg = self.batch_weights.pow(2).sum()
            loss += self.hparams.w_l2 * l2_reg
        
        
        c_scrub_loss = 0
        ### C-SCRuB section
        for a in self.unique_bs:
                                              
            ## designed so that the C-SCRuB object keeps the mu
            c_scrub_loss += self.C_SCRuB_Layers[str(a)]\
                                        .log_likelihood()
        
        loss -= c_scrub_loss
        

        loss /= float( x.size(0) )
        
        return {"loss": loss}

    def validation_step(self, batch: Tuple[Tensor, Tensor], batch_idx: int) -> Dict[str, Tensor]:
        
         # update the overall Gamma from all the updated Gamma within the batch-specific C-SCRuB objects
        p = torch.cat([ self.C_SCRuB_Layers[str(batch)].p for batch in self.unique_bs]).unsqueeze(-1)\
                        [torch.cat([ self.C_SCRuB_Layers[str(batch)].overall_dataset_inds for batch in self.unique_bs ] )]
       
        
        x, y, indices = batch
        x = x.view(x.size(0), -1)
        y_hat = self.forward(x, p[indices])
        
        
         # PyTorch cross_entropy function combines log_softmax and nll_loss in single function
        loss = self.prediction_loss(y_hat, y, reduction="sum")
        
        # L1 regularizer
        if self.hparams.l1_strength > 0:
            l1_reg = self.linear.weight.abs().sum()
            loss += self.hparams.l1_strength * l1_reg

        # L2 regularizer
        if self.hparams.l2_strength > 0:
            l2_reg = self.linear.weight.pow(2).sum()
            loss += self.hparams.l2_strength * l2_reg
        
        self.log('val_loss', loss)
        return {"val_loss": loss}

    
    def reset_Cscrub_Xcorrs(self):
        
        for a in self.unique_bs:
            batch_debiased_X = \
                F.normalize(
                    torch.pow(2, self.batch_weights\
                            )[ torch.where(self.unique_bs==a)[0] ] * \
                      (self.X[ torch.where(self.bs==a)[0] ] ) , 
                                p=1)
            
            mu_numpy = self.C_SCRuB_Layers[str(a)].rank_mu.detach().numpy()[0]
            
            X_mu_corrs = torch.Tensor( 
                np.array([ spearmanr( batch_debiased_X[:, i], mu_numpy )[0] \
                                         for i in range(batch_debiased_X.shape[1]) ]) )
        
            X_mu_corrs[torch.isnan(X_mu_corrs)] = 0
            
            self.C_SCRuB_Layers[str(a)].corr_X=X_mu_corrs
    
    def validation_epoch_end(self, outputs: List[Dict[str, Tensor]]) -> Dict[str, Tensor]:
        acc = 0
        val_loss = torch.stack([x["val_loss"] for x in outputs]).mean()
        
        ## use DEBIAS space to inform C-SCRuB X - mu correlations
        self.reset_Cscrub_Xcorrs()
        
        return {"val_loss": val_loss}

    def test_step(self, batch: Tuple[Tensor, Tensor], batch_idx: int) -> Dict[str, Tensor]:
         # update the overall Gamma from all the updated Gamma within the batch-specific C-SCRuB objects
        p = torch.cat([ self.C_SCRuB_Layers[str(batch)].p for batch in self.unique_bs]).unsqueeze(-1)\
                        [torch.cat([ self.C_SCRuB_Layers[str(batch)].overall_dataset_inds for batch in self.unique_bs ] )]
       
        x, y, indices = batch
        x = x.view(x.size(0), -1)
        y_hat = self.forward(x, p[indices])
        acc = 0
        return {"test_loss": self.prediction_loss(y_hat, y),
                "acc": acc}

    def test_epoch_end(self, outputs: List[Dict[str, Tensor]]) -> Dict[str, Tensor]:
        acc = 0
        test_loss = torch.stack([x["test_loss"] for x in outputs]).mean()
        tensorboard_logs = {"test_ce_loss": test_loss, "test_acc": acc}
        progress_bar_metrics = tensorboard_logs
        return {"test_loss": test_loss,
                "log": tensorboard_logs,
                "progress_bar": progress_bar_metrics}

    def configure_optimizers(self) -> Optimizer:
        return self.optimizer(
                            self.parameters(), 
                              lr=self.hparams.learning_rate)
    
    @staticmethod
    def add_model_specific_args(parent_parser: ArgumentParser) -> ArgumentParser:
        parser = ArgumentParser(parents=[parent_parser], add_help=False)
        parser.add_argument("--learning_rate", type=float, default=0.0001)
        parser.add_argument("--input_dim", type=int, default=None)
        parser.add_argument("--num_classes", type=int, default=None)
        parser.add_argument("--bias", default="store_true")
        parser.add_argument("--batch_size", type=int, default=100)
        
        return parser
    
    
def DEBIASM_train_and_pred(mu, 
                           X_train, 
                           mu_val,
                           X_val, 
                           y_train, 
                           y_val,
                           batch_sim_strength=1,
                           w_l2 = 0,
                           batch_size=None,
                           learning_rate=0.005,
                           l2_strength=0,
                           includes_batches=False,
                           val_split=0.1, 
                           test_split=0,
                           min_epochs=50, 
                           verbose=False, 
                           prediction_loss=F.cross_entropy
                           ):
    
    
    x_tr_cnts = pd.Series(X_train[:, 0]).value_counts()
    for batch in x_tr_cnts[x_tr_cnts==1].index: ## correlation gives NaNs in 1-sample batches
        inds=X_train[:, 0]!=batch
        X_train=X_train[inds]
        y_train=y_train[inds]
        mu=mu[inds]
    
    
    if batch_size is None:
        batch_size=X_train.shape[0]
    
    baseline_mod = LogisticRegression(max_iter=2500)
    baseline_mod.fit(rescale( X_train[:, 1:]), y_train)
    
    
    indices_all = np.arange(X_train.shape[0] + X_val.shape[0])
    indices_just_train = indices_all[:X_train.shape[0]]
    
    
    best_val_loss = 1e9
    for n_model_iters in range(3):
        
        model = PL_C_SCRuB_DEBIASM(
                           X = torch.tensor( np.vstack((X_train, X_val))), 
                           mu = torch.tensor( np.hstack( (mu, mu_val) ) ),
                           indices= torch.tensor( indices_all ).long(),
                           batch_sim_strength = batch_sim_strength,
                           input_dim = X_train.shape[1]-1, 
                           num_classes = 2, 
                           batch_size = batch_size,
                           learning_rate = learning_rate,
                           l2_strength = l2_strength, 
                           w_l2 = w_l2, 
                           prediction_loss=prediction_loss
                           )
        

        ## initialize parameters to lbe similar to standard logistic regression
        model.linear.weight.data[0]=-torch.tensor( baseline_mod.coef_[0] )
        model.linear.weight.data[1]= torch.tensor( baseline_mod.coef_[0] )


        y_train = torch.tensor( y_train ).long().detach().numpy() #due to windows numpy bug

        if prediction_loss!=F.cross_entropy:
            y_train=to_categorical(y_train, num_classes=y_train.max() + 1)


        ## build pl dataloader
        dm = SklearnDataModule(X_train, 
                               y_train,
                               indices_just_train,
                               val_split=val_split,
                               test_split=test_split
                               )

        ## run training
        trainer = pl.Trainer(logger=False, 
                             enable_checkpointing=False,
                             callbacks=[EarlyStopping(monitor="val_loss", mode="min", patience=2)], 
                             check_val_every_n_epoch=2, 
                             enable_model_summary=False, 
                             enable_progress_bar=False,
                             min_epochs=min_epochs, 
                             max_epochs=1000
                             )

        trainer.fit(model, 
                    train_dataloaders=dm.train_dataloader(), 
                    val_dataloaders=dm.val_dataloader()
                    )
        
        if trainer.callback_metrics.get("val_loss").item() < best_val_loss:
            best_model=model
            best_val_loss = trainer.callback_metrics.get("val_loss").item()
    
    model=best_model
    
    p = torch.cat([ model.C_SCRuB_Layers[str(batch)].p for batch in model.unique_bs]).unsqueeze(-1)\
                        [torch.cat([ model.C_SCRuB_Layers[str(batch)].overall_dataset_inds for batch in model.unique_bs ] )]
       
    
    
    ## get val predictions
    val_preds = model.forward( torch.tensor( X_val ).float(), 
                               p[ indices_all[X_train.shape[0]:] ]
                              )[:, 1].detach().numpy()

    ## return predictions and the model

    val_p = p[ indices_all[X_train.shape[0]:] ]
    train_p = p[ indices_all[: X_train.shape[0]] ]

    return( val_preds, model, val_p, train_p)


















