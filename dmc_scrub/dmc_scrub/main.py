import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from torch.nn.functional import pairwise_distance
from sklearn.base import BaseEstimator

from .torch_functions import DEBIASM_train_and_pred

from torch.nn.functional import cross_entropy

import torch.nn.functional as F

import logging
logging.getLogger("lightning.pytorch").setLevel(logging.ERROR)
logging.getLogger("pytorch_lightning").setLevel(logging.ERROR)



def batch_weight_feature_and_nbatchpairs_scaling(strength, df_with_batch):
    nbs = df_with_batch.iloc[:, 0].nunique()
    w = nbs * (nbs - 1) / 2
    return(strength /( w * ( df_with_batch.shape[1] - 1 ) ) )

class DMC_SCRuB_Classifier(BaseEstimator):
    """DebiasMClassifier: an sklean-style wrapper for the DEBIAS-M torch implementation."""
    def __init__(self,
                 *, 
                 batch_str = 'infer',
                 learning_rate=0.005, 
                 min_epochs=50,
                 l2_strength=0,
                 w_l2=0,
                 random_state=None,
                 x_val=0,
                 mu_val=0,
                 prediction_loss=cross_entropy,
                 ):
        
        self.learning_rate=learning_rate
        self.min_epochs=min_epochs
        self.l2_strength=l2_strength
        self.w_l2=w_l2
        self.batch_str=batch_str
        self.x_val = x_val
        self.mu_val = mu_val
        self.random_state=random_state
        self.prediction_loss=prediction_loss
#         self.lambda2=lambda2
#         self.lambda1=lambda1
        
    def fit(self, X, y, mu, sample_weight=None):
        """Fit the baseline classifier.

        Returns
        -------
        self : object
            Returns the instance itself.
        """
        
        if self.batch_str=='infer':
            self.batch_str = batch_weight_feature_and_nbatchpairs_scaling(1e4, pd.DataFrame(np.vstack((X, self.x_val)) ) )
            
        
        self.classes_ = np.unique(y)
        self.num_classes_ = self.classes_.shape[0]
        
        
        preds, mod, val_p, train_p = DEBIASM_train_and_pred(
                                                mu, ## new for C-SCRuB
                                                X, 
                                                self.mu_val,
                                                self.x_val, 
                                                y, 
                                                0,
                                                batch_sim_strength = self.batch_str,
                                                learning_rate=self.learning_rate,
                                                min_epochs= self.min_epochs,
                                                l2_strength=self.l2_strength,
                                                w_l2 = self.w_l2,
                                                prediction_loss=self.prediction_loss, 
                                                )
        
        self.x_train=X
            
            
            
            
        self.model = mod
        self.val_preds = preds
        
        self.val_p=val_p
        self.train_p=train_p
        
        
        return self
    
    def c_scrub_transform(self, self_model, x, p):
        batch_inds, x = x[:, 0], x[:, 1:]

        x = F.normalize( torch.pow(2, self_model.batch_weights[batch_inds.long()] ) * x, p=1 )


        x -= ( torch.cat([ self_model.C_SCRuB_Layers[str(batch)].gamma.unsqueeze(0)
                                                     for batch in batch_inds.long() ], 
                                    dim=0 ) * ( 1 - p ) )

        x = F.normalize( F.relu(x), p=1 )
        return(x)
    
    def transform(self):
        if self.model is None:
            raise(ValueError('You must run the `.fit()` method before executing this transformation'))
            
        return({'Train_X': self.c_scrub_transform(self.model, torch.tensor(self.x_train), self.train_p), 
                'Test_X': self.c_scrub_transform(self.model, torch.tensor(self.x_val), self.val_p)
               })

    def predict(self):
        """Perform classification on test vectors x_val.

        Parameters
        ----------

        Returns
        -------
        y : array-like of shape (n_samples,) or (n_samples, n_outputs)
            Predicted target values for X.
        """
        
        return(self.val_preds>0.5)
    

    def predict_proba(self):
        """
        Return probability estimates for the test vectors x_val.

        Parameters
        ----------

        Returns
        -------
        P : ndarray of shape (n_samples, n_classes) or list of such arrays
            Returns the probability of the sample for each class in
            the model, where classes are ordered arithmetically, for each
            output.
        """
        
        return(self.val_preds)
