# DMC-SCRuB


# Installation
```bash
pip install git+https://github.com/korem-lab/DMC-SCRuB.git
```



# Example
```python
import numpy as np
import dmc_scrub

## generate random example data
n_samples=384
n_feats=100
X = np.random.rand(n_samples, n_feats)
mu = np.random.rand(n_samples)
batches = np.array([i//96 for i in range(X.shape[0])])[:, np.newaxis]
X_with_batch = np.hstack([batches, X ])
y = np.random.rand(n_samples)>0.5

# DMC-SCRuB Example

test_inds = X_with_batch[:, 0]==3
dmcscr = dmc_scrub.DMC_SCRuB_Classifier(x_val=X_with_batch[test_inds],
                                        mu_val=mu[test_inds]
                                        )

dmcscr.fit(X_with_batch[~test_inds], 
           ( np.random.rand( X_with_batch.shape[0])>0.5 ).astype(float)[~test_inds], 
           mu[~test_inds]
           )


test_preds = dmcscr.predict_proba()

transformed = dmcscr.transform()
    # transformed['Train_X']
    # transformed['Test_X']
    
# C-SCRuB Example (single batch)

cscr = dmc_scrub.C_SCRuB()
cscr_out = cscr.fit_transform(
                      X[X_with_batch[:, 0]==3], 
                      mu[X_with_batch[:, 0]==3]
                      )
```





