import numpy as np
import torch
import copy

from mlutils.layers.cores import Stacked2dCore
from mlutils.layers.legacy import Gaussian2d
from mlutils.layers.readouts import PointPooled2d
from nnfabrik.utility.nn_helpers import get_module_output, set_random_seed, get_dims_for_loader_dict
from torch import nn
from torch.nn import functional as F

from .readouts import MultipleFullGaussian2d, MultiReadout, MultipleSpatialXFeatureLinear
from .utility import unpack_data_info

from ptrnets.cores.cores import TaskDrivenCore, TaskDrivenCore2


class Encoder(nn.Module):
    """
    helper nn class that combines the core and readout into the final model
    """
    def __init__(self, core, readout, elu_offset):
        super().__init__()
        self.core = core
        self.readout = readout
        self.offset = elu_offset

    def forward(self, x, data_key=None, **kwargs):
        x = self.core(x)
        x = self.readout(x, data_key=data_key)
        return F.elu(x + self.offset) + 1

    def regularizer(self, data_key):
        return self.readout.regularizer(data_key=data_key) + self.core.regularizer()


def task_core_gauss_readout(dataloaders, seed,
                            input_channels=1, model_name='vgg19',  # begin of core args
                            layer_name='features.10', pretrained=True, bias = False,
                            final_batchnorm=True, final_nonlinearity=True,
                            momentum=0.1,fine_tune=False,
                            init_mu_range=0.4, init_sigma_range=0.6, # readout args,
                            readout_bias=True, gamma_readout=0.01, gauss_type='isotropic',
                            elu_offset=-1, data_info=None # output and data_info
                           ):
    """
    A Model class of a predefined core (using models from ptrnets). Can be initialized pretrained or random.
    Can also be set to be trainable or not, independent of initialization.

    Args:
        dataloaders: a dictionary of train-dataloaders, one loader per session
            in the format {'data_key': dataloader object, .. }
        seed: ..
        pool_steps:
        pool_kern:
        readout_bias:
        init_range:
        gamma_readout:

    Returns:
    """

    if data_info is not None:
        n_neurons_dict, in_shapes_dict, input_channels = unpack_data_info(data_info)
    else:
        if "train" in dataloaders.keys():
            dataloaders = dataloaders["train"]


        # Obtain the named tuple fields from the first entry of the first dataloader in the dictionary
        in_name, out_name = next(iter(list(dataloaders.values())[0]))._fields

        session_shape_dict = get_dims_for_loader_dict(dataloaders)
        n_neurons_dict = {k: v[out_name][1] for k, v in session_shape_dict.items()}
        in_shapes_dict = {k: v[in_name] for k, v in session_shape_dict.items()}
        input_channels = [v[in_name][1] for v in session_shape_dict.values()]

    core_input_channels = list(input_channels.values())[0] if isinstance(input_channels, dict) else input_channels[0]

    set_random_seed(seed)

    core = TaskDrivenCore2(input_channels=core_input_channels,
                    model_name=model_name,
                    layer_name=layer_name,
                    pretrained=pretrained,
                    bias=bias,
                    final_batchnorm=final_batchnorm,
                    final_nonlinearity=final_nonlinearity,
                    momentum=momentum,
                    fine_tune=fine_tune)
    
    set_random_seed(seed)
    
    core.initialize()
    
    readout = MultipleFullGaussian2d(core, in_shape_dict=in_shapes_dict,
                                     n_neurons_dict=n_neurons_dict,
                                     init_mu_range=init_mu_range,
                                     init_sigma=init_sigma_range,
                                     bias=readout_bias,
                                     gamma_readout=gamma_readout,
                                     gauss_type=gauss_type,
                                     grid_mean_predictor=None, # not relevant for monkey data
                                     grid_mean_predictor_type=None, 
                                     source_grids=None,
                                     share_features=None, 
                                     share_grid=None, 
                                     shared_match_ids=None)
    

    if readout_bias and data_info is None:
        for key, value in dataloaders.items():
            _, targets = next(iter(value))
            readout[key].bias.data = targets.mean(0)

    model = Encoder(core, readout, elu_offset)

    return model



class MultiplePointPooled2d(MultiReadout, torch.nn.ModuleDict):
    def __init__(self, core, in_shape_dict, n_neurons_dict, pool_steps, pool_kern, bias, init_range, gamma_readout):
        # super init to get the _module attribute
        super(MultiplePointPooled2d, self).__init__()
        for k in n_neurons_dict:
            in_shape = get_module_output(core, in_shape_dict[k])[1:]
            n_neurons = n_neurons_dict[k]
            self.add_module(k, PointPooled2d(
                in_shape,
                n_neurons,
                pool_steps=pool_steps,
                pool_kern=pool_kern,
                bias=bias,
                init_range=init_range)
                            )
        self.gamma_readout = gamma_readout

def task_core_point_readout(dataloaders, seed,
                            input_channels=1, model_name='vgg19_original',  # begin of core args
                            layer_name='features.10', pretrained=True, bias = False,
                            final_batchnorm=True, final_nonlinearity=True,
                            momentum=0.1,fine_tune=False,
                            pool_steps=2, pool_kern=3, init_range=0.2, # readout args
                            readout_bias=True, gamma_readout=5.8,
                            elu_offset=-1, data_info=None # output and data_info
                           ):
    """
    A Model class of a predefined core (using models from ptrnets). Can be initialized pretrained or random.
    Can also be set to be trainable or not, independent of initialization.

    Args:
        dataloaders: a dictionary of train-dataloaders, one loader per session
            in the format {'data_key': dataloader object, .. }
        seed: ..
        pool_steps:
        pool_kern:
        readout_bias:
        init_range:
        gamma_readout:

    Returns:
    """

    if data_info is not None:
        n_neurons_dict, in_shapes_dict, input_channels = unpack_data_info(data_info)
    else:
        if "train" in dataloaders.keys():
            dataloaders = dataloaders["train"]


        # Obtain the named tuple fields from the first entry of the first dataloader in the dictionary
        in_name, out_name = next(iter(list(dataloaders.values())[0]))._fields

        session_shape_dict = get_dims_for_loader_dict(dataloaders)
        n_neurons_dict = {k: v[out_name][1] for k, v in session_shape_dict.items()}
        in_shapes_dict = {k: v[in_name] for k, v in session_shape_dict.items()}
        input_channels = [v[in_name][1] for v in session_shape_dict.values()]

    core_input_channels = list(input_channels.values())[0] if isinstance(input_channels, dict) else input_channels[0]

    set_random_seed(seed)

    core = TaskDrivenCore2(input_channels=core_input_channels,
                    model_name=model_name,
                    layer_name=layer_name,
                    pretrained=pretrained,
                    bias=bias,
                    final_batchnorm=final_batchnorm,
                    final_nonlinearity=final_nonlinearity,
                    momentum=momentum,
                    fine_tune=fine_tune)
    
    set_random_seed(seed)
    
    core.initialize()
    
    print(core)
    
    readout = MultiplePointPooled2d(core, in_shape_dict=in_shapes_dict,
                                    n_neurons_dict=n_neurons_dict,
                                    pool_steps=pool_steps,
                                    pool_kern=pool_kern,
                                    bias=readout_bias,
                                    gamma_readout=gamma_readout,
                                    init_range=init_range)

    if readout_bias and data_info is None:
        for key, value in dataloaders.items():
            _, targets = next(iter(value))
            readout[key].bias.data = targets.mean(0)

    model = Encoder(core, readout, elu_offset)

    return model

