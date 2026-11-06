import os
from setuptools import setup, find_packages

def read(fname):
    return open(os.path.join( os.path.dirname(__file__), fname) ).read()


setup(
    name='DMC-SCRuB',
    version='0.1.0',
    author='George I. Austin', 
    author_email='gia2105@columbia.edu', 
    url='https://github.com/korem-lab/DMC-SCRuB',
    packages=['dmc_scrub'],
    include_package_data=True,
    install_requires=['numpy', 
                      'scikit-learn', 
                      'pandas',
                      'torch', 
                      'scipy', 
                      'torchsort'
                     ]
)