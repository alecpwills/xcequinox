import jax, os, pickle
import jax.numpy as jnp
import equinox as eqx


class LOB(eqx.Module):
    limit: jax.Array
    sig: jax.named_call
    
    
    def __init__(self, limit=1.804):
        """
        __init__ Utility function to squash output to [-1, limit-1] inteval.

        Can be used to enforce non-negativity, Lieb-Oxford bounds, etc.
        Initializes method :self.sig: -- the :jax.nn.sigmoid: function, as well.

        :param limit: The Lieb-Oxford bound value to impose, defaults to 1.804
        :type limit: float, optional
        """
        super().__init__()
        self.sig = jax.nn.sigmoid
        self.limit = limit

    def __call__(self, x):
        """
        __call__ Method calling the actual mapping of the input to the desired bounded region.


        :param x: Energy value to map back into the bounded region.
        :type x: float
        :return: Energy value mapped into bounded region.
        :rtype: float
        """
        return self.limit*self.sig(x-jnp.log(self.limit-1))-1


class eX(eqx.Module):
    n_input: int
    n_hidden: int
    ueg_limit: jax.Array
    spin_scaling: bool
    lob: jax.Array
    use: list
    net: eqx.Module
    tanh: jax.named_call
    lobf: jax.named_call
    sig: jax.named_call
    shift: jax.Array
    lobf: eqx.Module
    seed: int
    depth: int

    def __init__(self, n_input, n_hidden=16, depth=3, use=[], ueg_limit=False, lob=1.804, seed=92017, spin_scaling=True):
        """
        __init__ Local exchange model based on MLP.

        Receives density descriptors in this order : [rho, s, alpha, nl], where the input may be truncated depending on XC-level of approximation.

        The MLP generated is hard-coded to have one output value -- the predicted exchange energy given a specific input from the grid.

        :param n_input: Input dimensions (LDA: 1, GGA: 2, meta-GGA: 3, ...)
        :type n_input: int
        :param n_hidden: Number of hidden nodes (three hidden layers used by default), defaults to 16
        :type n_hidden: int, optional
        :param depth: Depth of the MLP, defaults to 3
        :type depth: int, optional
        :param use: Only these indices are used as input to the model (can be used to omit density as input to enforce uniform density scaling). These indices are also used to enforce UEG where the assumed order is [s, alpha, ...], defaults to []
        :type use: list, optional
        :param ueg_limit: Flag to determine whether or not to enforce uniform homoegeneous electron gas limit, defaults to False
        :type ueg_limit: bool, optional
        :param lob: Enforce this value as local Lieb-Oxford bound (don't enforce if set to 0), defaults to 1.804
        :type lob: float, optional
        :param seed: Random seed used to generate initial weights and biases for the MLP, defaults to 92017
        :type seed: int, optional
        """
        super().__init__()
        self.ueg_limit = ueg_limit
        self.spin_scaling = spin_scaling
        self.lob = lob
        self.n_input = n_input
        self.n_hidden = n_hidden
        self.seed = seed
        self.depth = depth

        if not use:
            self.use = jnp.arange(n_input)
        else:
            self.use = use
        self.net =  eqx.nn.MLP(in_size = self.n_input,
                               out_size = 1,
                               width_size = self.n_hidden,
                               depth = self.depth,
                               activation = jax.nn.gelu,
                              key=jax.random.PRNGKey(self.seed))
        
        self.tanh = jnp.tanh
        self.lobf = LOB(limit=self.lob)
        self.sig = jax.nn.sigmoid
        self.shift = 1/(1+jnp.exp(-1e-3))

    def __call__(self, rho, **kwargs):
        """
        __call__ Forward pass for the exchange network.

        Uses :jax.vmap: to vectorize evaluation of the MLP on the descriptors, assuming a shape [batch, *, n_input]

        .. todo: Make sure the :vmap: call can work with specific :use: values beyond the defaults assumed in the previous implementation.

        :param rho: The descriptors to the MLP -- transformed densities and gradients appropriate to the XC-level. This network will only use the dimensions specified in self.use.
        :type rho: jax.Array
        :return: The exchange energy on the grid
        :rtype: jax.Array
        """
        print(f"eX.__call__, rho shape: {rho.shape}")
        if self.spin_scaling:
            squeezed = jnp.squeeze(jax.vmap(jax.vmap(self.net), in_axes=1)(rho[...,self.use])).T
        else:
            squeezed = jnp.squeeze(jax.vmap(self.net)(rho[..., self.use]))

        if self.ueg_limit:
            ueg_lim = rho[...,self.use[0]]
            if len(self.use) > 1:
                ueg_lim_a = jnp.power(self.tanh(rho[...,self.use[1]]),2)
            else:
                ueg_lim_a = 0
            if len(self.use) > 2:
                ueg_lim_nl = jnp.sum(rho[...,self.use[2:]],axis=-1)
            else:
                ueg_lim_nl = 0
        else:
            ueg_lim = 1
            ueg_lim_a = 0
            ueg_lim_nl = 0

        if self.lob:
            result = self.lobf(squeezed*(ueg_lim + ueg_lim_a + ueg_lim_nl))
        else:
            result = squeezed*(ueg_lim + ueg_lim_a + ueg_lim_nl)

        return result

class eC(eqx.Module):
    n_input: int
    n_hidden: int
    ueg_limit: jax.Array
    spin_scaling: bool
    lob: jax.Array
    use: list
    net: eqx.Module
    tanh: jax.named_call
    lobf: jax.named_call
    sig: jax.named_call
    lobf: eqx.Module
    seed: int
    depth: int

    def __init__(self, n_input=2,n_hidden=16, depth=3, use = [], ueg_limit=False, lob=2.0, seed=92017, spin_scaling = False):
        """
        __init__ Local correlation model based on MLP.

        Receives density descriptors in this order : [rho, spinscale, s, alpha, nl], where the input may be truncated depending on XC-level of approximation

        .. todo: Make sure the :vmap: call can work with specific :use: values beyond the defaults assumed in the previous implementation.

        :param n_input: Input dimensions (LDA: 2, GGA: 3 , meta-GGA: 4), defaults to 2.
        :type n_input: int
        :param n_hidden: Number of hidden nodes (three hidden layers used by default), defaults to 16
        :type n_hidden: int, optional
        :param depth: Depth of the MLP, defaults to 3
        :type depth: int, optional
        :param use: Only these indices are used as input to the model. These indices are also used to enforce UEG where the assumed order is [s, alpha, ...], defaults to []
        :type use: list, optional
        :param ueg_limit: Flag to determine whether or not to enforce uniform homoegeneous electron gas limit, defaults to False
        :type ueg_limit: bool, optional
        :param lob: Enforce this value as local Lieb-Oxford bound (don't enforce if set to 0), defaults to 2.0
        :type lob: float, optional
        :param seed: Random seed used to generate initial weights and biases for the MLP, defaults to 92017
        :type seed: int, optional
        """
        super().__init__()
        self.spin_scaling = spin_scaling
        self.lob = False
        self.ueg_limit = ueg_limit
        self.n_input=n_input
        self.n_hidden=n_hidden
        self.seed = seed
        self.depth = depth

        if not use:
            self.use = jnp.arange(n_input)
        else:
            self.use = use
        self.net =  eqx.nn.MLP(in_size = self.n_input,
                               out_size = 1,
                               width_size = self.n_hidden,
                               depth = self.depth,
                               activation = jax.nn.gelu,
                               final_activation = jax.nn.softplus,
                               key=jax.random.PRNGKey(self.seed))
        self.sig = jax.nn.sigmoid
        self.tanh = jnp.tanh
        self.lob = lob
        if self.lob:
            self.lobf = LOB(self.lob)
        else:
            self.lob =  1000.0
            self.lobf = LOB(self.lob)


    def __call__(self, rho, **kwargs):
        """
        __call__ Forward pass for the correlation network.

        Uses :jax.vmap: to vectorize evaluation of the MLP on the descriptors, assuming a shape [*, n_input]

        :param rho: The descriptors to the MLP -- transformed densities and gradients appropriate to the XC-level. This network will only use the dimensions specified in self.use in determining the UEG limits.
        :type rho: jax.Array
        :return: The exchange energy on the grid
        :rtype: jax.Array
        """
        print(f"eC.__call__, rho shape: {rho.shape}")
        if self.spin_scaling:
            squeezed = -jnp.squeeze(jax.vmap(jax.vmap(self.net), in_axes=1)(rho[...,self.use])).T
        else:
            squeezed = -jnp.squeeze(jax.vmap(self.net)(rho[..., self.use]))

        if self.ueg_limit:
            ueg_lim = self.tanh(rho[...,self.use[0]])
            if len(self.use) > 1:
                ueg_lim_a = jnp.pow(self.tanh(rho[...,self.use[1]]),2)
            else:
                ueg_lim_a = 0
            if len(self.use) > 2:
                ueg_lim_nl = jnp.sum(self.tanh(rho[...,self.use[2:]])**2,axis=-1)
            else:
                ueg_lim_nl = 0

            ueg_factor = ueg_lim + ueg_lim_a + ueg_lim_nl
        else:
            ueg_factor = 1
        if self.lob:
            return self.lobf(squeezed*ueg_factor)
        else:
            return squeezed*ueg_factor



def make_net(xorc, level, depth, nhidden, ninput = None, use = None, spin_scaling = None, lob = None, ueg_limit = None,
                random_seed = None, savepath = None, configfile = 'network.config'):
    '''
    make_net is a utility function designed to easily create new, individual exchange or correlation networks with ease. If no extra arguments are specified, the network will be generated with a default structure that respects the various constraints implemented within xcquinox

    :param xorc: 'X' or 'C' -- the type of network to generate, exchange or correlation
    :type xorc: str
    :param level: one of ['GGA', 'MGGA', 'NONLOCAL', 'NL'], indicating the desired rung of Jacob's Ladder. NONLOCAL = NL
    :type level: str
    :param depth: The number of hidden layers in the generated network.
    :type depth: int
    :param nhidden: The number of nodes in a hidden layer
    :type nhidden: int
    :param ninput: The number of inputs the network will expect, defaults to None for automatic selection based on level
    :type ninput: int, optional
    :param use: The indices of the descriptors to evaluate the network on, defaults to None
    :type use: list of ints, optional
    :param spin_scaling: Whether or not to enforce the spin-scaling contraint in the generated network, defaults to None
    :type spin_scaling: bool, optional
    :param lob: Lieb-Oxford bound: If non-zero (i.e., truthy), the output values of e_x or e_c will be squashed between [-1, lob-1], defaults to None
    :type lob: float, optional
    :param ueg_limit: Whether or not to enforce the UEG scaling constraint, defaults to None
    :type ueg_limit: bool, optional
    :param random_seed: The random seed to use in generating initial network weights, defaults to None
    :type random_seed: int, optional
    :param savepath: Location to save the generated network and associated config file, defaults to None
    :type savepath: str, optional
    :param configfile: Name for the configuration file, needed when reading in the network to re-generate the same structure, defaults to 'network.config'
    :type configfile: str, optional
    :return: The resulting exchange or correlation network.
    :rtype: :xcquinox.net.eX: or :xcquinox.net.eC:
    '''
    defaults_dct = {'GGA': {'X': {'ninput' : 1, 'depth': 3, 'nhidden': 16, 'use': [1], 'spin_scaling': True, 'lob': 1.804, 'ueg_limit':True},
                            'C': {'ninput': 1, 'depth': 3, 'nhidden': 16, 'use': [2], 'spin_scaling': False, 'lob': 2.0, 'ueg_limit':True}
                           },
                    'MGGA': {'X': {'ninput' : 2, 'depth': 3, 'nhidden': 16, 'use': [1, 2], 'spin_scaling': True, 'lob': 1.174, 'ueg_limit':True},
                            'C': {'ninput': 2, 'depth': 3, 'nhidden': 16, 'use': [2, 3], 'spin_scaling': False, 'lob': 2.0, 'ueg_limit':True}
                           },
                    'NL': {'X': {'ninput' : 15, 'depth': 3, 'nhidden': 16, 'use': None, 'spin_scaling': True, 'lob': 1.174, 'ueg_limit':True},
                            'C': {'ninput': 16, 'depth': 3, 'nhidden': 16, 'use': None, 'spin_scaling': False, 'lob': 2.0, 'ueg_limit':True}
                           }
                   }
    assert level.upper() in ['GGA', 'MGGA', 'NONLOCAL', 'NL']

    ninput = ninput if ninput is not None else defaults_dct[level.upper()][xorc.upper()]['ninput']
    depth = depth if depth is not None else defaults_dct[level.upper()][xorc.upper()]['depth']
    nhidden = nhidden if nhidden is not None else defaults_dct[level.upper()][xorc.upper()]['nhidden']
    use = use if use is not None else defaults_dct[level.upper()][xorc.upper()]['use']
    spin_scaling = spin_scaling if spin_scaling is not None else defaults_dct[level.upper()][xorc.upper()]['spin_scaling']
    ueg_limit = ueg_limit if ueg_limit is not None else defaults_dct[level.upper()][xorc.upper()]['ueg_limit']
    lob = lob if lob is not None else defaults_dct[level.upper()][xorc.upper()]['lob']
    random_seed = random_seed if random_seed is not None else 92017
    config = {'ninput':ninput,
              'depth':depth,
              'nhidden':nhidden,
              'use':use,
              'spin_scaling':spin_scaling,
              'ueg_limit': ueg_limit,
              'lob':lob,
             'random_seed': random_seed}
    if xorc.upper() == 'X':    
        net = eX(n_input=ninput, use=use, depth=depth, n_hidden=nhidden, spin_scaling=spin_scaling, lob=lob, seed=random_seed)
    elif xorc.upper() == 'C':
        net = eC(n_input=ninput, use=use, depth=depth, n_hidden=nhidden, spin_scaling=spin_scaling, lob=lob, seed=random_seed)
    
    if savepath:
        try:
            os.makedirs(savepath)
        except Exception as e:
            print(e)
            print(f'Exception raised in creating {savepath}.')
        with open(os.path.join(savepath, configfile), 'w') as f:
            for k, v in config.items():
                f.write(f'{k}\t{v}\n')
        with open(os.path.join(savepath, configfile+'.pkl'), 'wb') as f:
            pickle.dump(config, f)
        eqx.tree_serialise_leaves(os.path.join(savepath, 'xc.eqx'), net)

    return net, config

def get_net(xorc, level, net_path, configfile='network.config', netfile='xc.eqx'):
    '''
    A utility function to easily load in a previously generated network. Functionally creates a random network of the same architecture, then overwrites the weights with those of the saved network.

    :param xorc: 'X' or 'C' -- the type of network to generate, exchange or correlation
    :type xorc: str
    :param level: one of ['GGA', 'MGGA', 'NONLOCAL', 'NL'], indicating the desired rung of Jacob's Ladder. NONLOCAL = NL
    :type level: str
    :param net_path: Location of the saved network. Must have a {configfile}.pkl parameter file within.
    :type net_path: str
    :param configfile: Name for the configuration file, needed when reading in the network to re-generate the same structure, defaults to 'network.config'
    :type configfile: str, optional
    :param netfile: Name for the network file, needed when reading in the network overwrite generated random weights, defaults to 'xc.eqx'. If Falsy, just generates random network based on config file.
    :type netfile: str, optional
    :return: The requested exchange or correlation network.
    :rtype: :xcquinox.net.eX: or :xcquinox.net.eC:
    '''
    with open(os.path.join(net_path, configfile+'.pkl'), 'rb') as f:
        params = pickle.load(f)
    #network parameters
    depth = params['depth']
    nodes = params['nhidden']
    use = params['use']
    inp = params['ninput']
    ss = params['spin_scaling']
    lob = params['lob']
    ueg = params['ueg_limit']
    seed = params['random_seed']

    net, _ = make_net(xorc=xorc, level=level, depth=depth, nhidden=nodes, ninput=inp, use=use,
                       spin_scaling = ss, lob = lob, ueg_limit = ueg, random_seed = seed, configfile=configfile)
    if netfile:
        #make sure the netfile is actually there
        netfs = [i for i in os.listdir(net_path) if netfile in i]
        #if multiple returned, there was training to take place -- sort and select last checkpoint
        if len(netfs) == 1:
            print('SINGLE NETFILE MATCH FOUND. DESERIALIZING...')
            net = eqx.tree_deserialise_leaves(os.path.join(net_path, netfs[0]), net)
        elif len(netfs) > 1:
            print('NETFILE MATCHES FOUND -- MULTIPLE. SELECTING LAST ONE.')
            netf = sorted(netfs, key=lambda x: int(x.split('.')[-1]))[-2]
            print('ATTEMPTING TO DESERIALIZE {}'.format(netf))
            net = eqx.tree_deserialise_leaves(os.path.join(net_path, netf), net)
        else:
            print('NETFILE SPECIFIED BUT NO MATCHING FILE FOUND.')


    return net, params
