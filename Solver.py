import logging
import mxnet as mx
import numpy as np

def save_checkpoint(prefix, epoch, symbol, arg_params, aux_params):
    """Checkpoint the model data into file.

    Parameters
    ----------
    prefix : str
        Prefix of model name.
    epoch : int
        The epoch number of the model.
    symbol : Symbol
        The input symbol
    arg_params : dict of str to NDArray
        Model parameter, dict of name to NDArray of net's weights.
    aux_params : dict of str to NDArray
        Model parameter, dict of name to NDArray of net's auxiliary states.
    Notes
    -----
    - ``prefix-symbol.json`` will be saved for symbol.
    - ``prefix-epoch.params`` will be saved for parameters.
    """
    symbol.save('%s-symbol.json' % prefix)
    save_dict = {('arg:%s' % k) : v.copyto(mx.cpu()) for k, v in arg_params.items()}
    save_dict.update({('aux:%s' % k) : v.copyto(mx.cpu()) for k, v in aux_params.items()})
    param_name = '%s-%04d.params' % (prefix, epoch)
    mx.nd.save(param_name, save_dict)
    logging.info('Saved checkpoint to (ctx=cpu) \"%s\"', param_name)


class CarReID_Solver(object):
  def __init__(self, prefix='', symbol=None, ctx=None, data_shape=None, label_shape=None,
               num_epoch=None, opt_method='sgd', **kwargs):
    self.prefix = prefix
    self.symbol = symbol
    self.ctx = ctx
    if self.ctx is None:
        self.ctx = mx.cpu()
    self.data_shape = data_shape
    self.label_shape = label_shape
    self.batchsize = data_shape[0]
    self.num_epoch = num_epoch
    self.update_params = None
    self.arg_params = None
    self.aux_params = None
    self.grad_params = None
    self.executor = None
    self.opt_method = opt_method
    self.optimizer = None
    self.updater = None
    self.kwargs = kwargs.copy()
    self.initializer=mx.init.Xavier()

  def init_args(self, args):
    for key in args:
      arr = args[key]
      if key.endswith('_weight'):
        self.initializer(key, arr) 
      if key.endswith('_bias'):
        arr[:] = 0.0
      if key.endswith('_gamma'):
        arr[:] = 1.0
      if key.endswith('_beta'):
        arr[:] = 0.0
      if key.endswith('_init_c'):
        arr[:] = 0.0
      if key.endswith('_init_h'):
        arr[:] = 0.0

  def get_params(self, grad_req):
    arg_names = self.symbol.list_arguments()
    arg_shapes, _, aux_shapes = \
                self.symbol.infer_shape(part1_data=self.data_shape, 
                                        part2_data=self.data_shape,
                                        label=self.label_shape)

    self.arg_params = {}
    self.update_params = {}
    for name, shape in zip(arg_names, arg_shapes):
      self.arg_params[name] = mx.nd.zeros(shape, self.ctx)
      if name.endswith('weight') or name.endswith('bias') or name.endswith('gamma') or name.endswith('beta'):
#        print name
        self.update_params[name] = self.arg_params[name]

    self.init_args(self.arg_params)

    if grad_req != 'null':
      self.grad_params = {}
      for name, shape in zip(arg_names, arg_shapes):
        self.grad_params[name] = mx.nd.zeros(shape, self.ctx)
    aux_names = self.symbol.list_auxiliary_states()
    self.aux_params = {k: mx.nd.zeros(s, self.ctx) for k, s in zip(aux_names, aux_shapes)}

  def set_params(self, whichone):
    logging.info('loading checkpoint from %s-->%d...', self.prefix, whichone)
    loadfunc = mx.model.load_checkpoint
    self.symbol, update_params, aux_params = loadfunc(self.prefix, whichone)
    for name in self.update_params:
      self.arg_params[name][:] = update_params[name]
    for name in self.aux_params:
      self.aux_params[name][:] = aux_params[name]
#    name = 'PART2_COV_5_bn_moving_mean'
#    print name, aux_params[name].asnumpy()
#    exit()
    return

  def fit(self, train_data, grad_req='write', showperiod=100, whichone=None, logger=None):
    if logger is not None:
      logger.info('Start training with %s', str(self.ctx))

    savefunc = save_checkpoint

    self.get_params(grad_req)
    if whichone is not None:
      self.set_params(whichone)
    self.optimizer = mx.optimizer.create(self.opt_method, rescale_grad=(1.0 / self.batchsize), **self.kwargs)
    self.updater = mx.optimizer.get_updater(self.optimizer)
    self.executor = self.symbol.bind(self.ctx, self.arg_params, args_grad=self.grad_params,
                                     grad_req=grad_req, aux_states=self.aux_params)
    update_dict = self.update_params
#    epoch_end_callback = mx.callback.do_checkpoint(self.prefix)
 
    # begin training
    for epoch in range(0, self.num_epoch):
      nbatch = 0
      train_data.reset()
      num_batches = train_data.num_batches
      cost = [] 
      for databatch in train_data:
        nbatch += 1
        for k, v in databatch.data.items():
       #   print k, v.shape
          self.arg_params[k][:] = mx.nd.array(v, self.ctx)
        for k, v in databatch.label.items():
       #   print k, v.shape
          self.arg_params[k][:] = mx.nd.array(v, self.ctx)
        output_dict = {name: nd for name, nd in zip(self.symbol.list_outputs(), self.executor.outputs)}
        self.executor.forward(is_train=True)
        self.executor.backward()

        for key in update_dict:
#          print key, np.sum(arr.asnumpy())
          arr = self.grad_params[key]
          self.updater(key, arr, self.arg_params[key])

        outval = output_dict['reid_loss_output'].asnumpy()
        outval = np.mean(outval)
        cost.append(outval)
        lrsch = self.optimizer.lr_scheduler
        step = lrsch.step
        nowlr = lrsch.base_lr
        num_update = self.optimizer.num_update
        if num_update % showperiod == 0:
          print num_update, 'cost:', np.mean(cost), 'lr:', nowlr, num_batches 
          cost = []
#          epoch_end_callback(epoch, self.symbol, self.update_params, self.aux_params)
          savefunc(self.prefix, epoch%10, self.symbol, self.update_params, self.aux_params)
#          print databatch.label['label'].T


class CarReID_Proxy_Solver(object):
  def __init__(self, prefix='', symbol=None, ctx=None, data_shape=None, label_shape=None,
               num_epoch=None, falsebigbatch=1, opt_method='sgd', **kwargs):
    self.prefix = prefix
    self.symbol = symbol
    self.ctx = ctx
    if self.ctx is None:
        self.ctx = mx.cpu()
    self.data_shape = data_shape
    self.label_shape = label_shape
    self.batchsize = data_shape[0]
    self.num_epoch = num_epoch
    self.update_params = None
    self.falsebigbatch = falsebigbatch
    print 'false big batch size:%d*%d=%d'%(falsebigbatch, self.batchsize, falsebigbatch * self.batchsize)
    self.arg_params = None
    self.aux_params = None
    self.grad_params = None
    self.executor = None
    self.opt_method = opt_method
    self.optimizer = None
    self.updater = None
    self.kwargs = kwargs.copy()
    self.initializer=mx.init.Xavier()

  def init_args(self, args):
    for key in args:
      arr = args[key]
      if key.endswith('_weight'):
#        self.initializer(mx.init.InitDesc(key), arr) 
        self.initializer(key, arr) 
      if key.endswith('_bias'):
        arr[:] = 0.0
      if key.endswith('_gamma'):
        arr[:] = 1.0
      if key.endswith('_beta'):
        arr[:] = 0.0
      if key.endswith('_init_c'):
        arr[:] = 0.0
      if key.endswith('_init_h'):
        arr[:] = 0.0

  def get_params(self, grad_req):
    arg_names = self.symbol.list_arguments()
    arg_shapes, _, aux_shapes = \
                self.symbol.infer_shape(data=self.data_shape, 
                                        **self.label_shape)

    self.arg_params = {}
    self.update_params = {}
    for name, shape in zip(arg_names, arg_shapes):
#      print name, shape
      self.arg_params[name] = mx.nd.zeros(shape, self.ctx)
      if name.endswith('weight') or name.endswith('bias') or \
          name.endswith('gamma') or name.endswith('beta') or \
          name=='proxy_Z':
#        print name
        self.update_params[name] = self.arg_params[name]

    self.init_args(self.arg_params)

    if grad_req != 'null':
      self.grad_params = {}
      self.bigbatch_grads = {}
      for name, shape in zip(arg_names, arg_shapes):
        self.grad_params[name] = mx.nd.zeros(shape, self.ctx)
        self.bigbatch_grads[name] = mx.nd.zeros(shape, self.ctx)
    aux_names = self.symbol.list_auxiliary_states()
    self.aux_params = {k: mx.nd.zeros(s, self.ctx) for k, s in zip(aux_names, aux_shapes)}

  def set_params(self, whichone):
    logging.info('loading checkpoint from %s-->%d...', self.prefix, whichone)
    loadfunc = mx.model.load_checkpoint
    _, update_params, aux_params = loadfunc(self.prefix, whichone)
    for name in self.update_params:
      self.arg_params[name][:] = update_params[name]
    for name in self.aux_params:
      self.aux_params[name][:] = aux_params[name]
#    name = 'PART2_COV_5_bn_moving_mean'
#    print name, aux_params[name].asnumpy()
#    exit()
    return

  def fit(self, train_data, grad_req='write', showperiod=100, whichone=None, logger=None):
    if logger is not None:
     
      logger.info('Start training with %s', str(self.ctx))

    savefunc = save_checkpoint

    self.get_params(grad_req)
    if whichone is not None:
      self.set_params(whichone)
    else:
      import DataGenerator as dg
      proxyfn = 'proxy.bin'
      proxy_set = dg.get_proxyset(proxyfn, self.arg_params['proxy_Z'].shape)
      self.arg_params['proxy_Z'][:] = mx.nd.array(proxy_set, self.ctx)

    self.optimizer = mx.optimizer.create(self.opt_method, rescale_grad=(1.0 / self.batchsize), **self.kwargs)
    self.updater = mx.optimizer.get_updater(self.optimizer)
    self.executor = self.symbol.bind(self.ctx, self.arg_params, args_grad=self.grad_params,
                                     grad_req=grad_req, aux_states=self.aux_params)
    update_dict = self.update_params
#    epoch_end_callback = mx.callback.do_checkpoint(self.prefix)
 
    # begin training
    cost = [] 
    nbatch = 0
    for epoch in range(0, self.num_epoch):
      train_data.reset()
      num_batches = train_data.num_batches
      for databatch in train_data:
        nbatch += 1
        for ks, v in zip(train_data.provide_data, databatch.data):
          k = ks[0]
          self.arg_params[k][:] = v
        for ks, v in zip(train_data.provide_label, databatch.label):
          k = ks[0]
          self.arg_params[k][:] = v
        output_dict = {name: nd for name, nd in zip(self.symbol.list_outputs(), self.executor.outputs)}
        self.executor.forward(is_train=True)
        self.executor.backward()

        for key in update_dict:
          arr = self.grad_params[key]
          self.bigbatch_grads[key][:] = self.bigbatch_grads[key] + arr

        if nbatch%self.falsebigbatch==0:
#          print nbatch, self.bigbatchnum
          for key in update_dict:
            arr = self.grad_params[key]
            arr[:] = self.bigbatch_grads[key] / self.falsebigbatch
            self.updater(key, arr, self.arg_params[key])
            self.bigbatch_grads[key][:] = 0

        outval = output_dict['proxy_nca_loss_output'].asnumpy()
#        print np.mean(outval)

        cost.append(np.mean(outval))
        lrsch = self.optimizer.lr_scheduler
        step = lrsch.step
        nowlr = lrsch.base_lr
        num_update = nbatch 
        if num_update % showperiod == 0:
          print num_update, 'cost:', np.mean(cost), 'lr:', nowlr, num_batches  
          cost = []
          savefunc(self.prefix, epoch%10, self.symbol, self.update_params, self.aux_params)
##          print databatch.label['label'].T


class CarReID_Softmax_Solver(object):
  def __init__(self, prefix='', symbol=None, ctx=None, data_shape=None, label_shape=None,
               num_epoch=None, falsebigbatch=1, opt_method='sgd', **kwargs):
    self.prefix = prefix
    self.symbol = symbol
    self.ctx = ctx
    if self.ctx is None:
        self.ctx = mx.cpu()
    self.data_shape = data_shape
    self.label_shape = label_shape
    self.batchsize = data_shape[0]
    self.num_epoch = num_epoch
    self.update_params = None
    self.arg_params = None
    self.aux_params = None
    self.grad_params = None
    self.executor = None
    self.opt_method = opt_method
    self.optimizer = None
    self.falsebigbatch = falsebigbatch
    print 'false big batch size:%d*%d=%d'%(falsebigbatch, self.batchsize, falsebigbatch * self.batchsize)
    self.bigbatch_grads = None
    self.updater = None
    self.kwargs = kwargs.copy()
    self.initializer=mx.init.Xavier()

  def init_args(self, args):
    for key in args:
      arr = args[key]
      if key.endswith('_weight'):
        self.initializer(key, arr) 
      if key.endswith('_bias'):
        arr[:] = 0.0
      if key.endswith('_gamma'):
        arr[:] = 1.0
      if key.endswith('_beta'):
        arr[:] = 0.0
      if key.endswith('_init_c'):
        arr[:] = 0.0
      if key.endswith('_init_h'):
        arr[:] = 0.0

  def get_params(self, grad_req):
    arg_names = self.symbol.list_arguments()
    arg_shapes, _, aux_shapes = \
                self.symbol.infer_shape(data=self.data_shape, 
                                        label=self.label_shape)

    self.arg_params = {}
    self.update_params = {}
    for name, shape in zip(arg_names, arg_shapes):
      self.arg_params[name] = mx.nd.zeros(shape, self.ctx)
      if name.endswith('weight') or name.endswith('bias') or name.endswith('gamma') or name.endswith('beta'):
#        print name
        self.update_params[name] = self.arg_params[name]

    self.init_args(self.arg_params)

    if grad_req != 'null':
      self.grad_params = {}
      self.bigbatch_grads = {}
      for name, shape in zip(arg_names, arg_shapes):
        self.grad_params[name] = mx.nd.zeros(shape, self.ctx)
        self.bigbatch_grads[name] = mx.nd.zeros(shape, self.ctx)

    aux_names = self.symbol.list_auxiliary_states()
    self.aux_params = {k: mx.nd.zeros(s, self.ctx) for k, s in zip(aux_names, aux_shapes)}

  def set_params(self, whichone):
    logging.info('loading checkpoint from %s-->%d...', self.prefix, whichone)
    loadfunc = mx.model.load_checkpoint
    self.symbol, update_params, aux_params = loadfunc(self.prefix, whichone)
    for name in self.update_params:
      self.arg_params[name][:] = update_params[name]
    for name in self.aux_params:
      self.aux_params[name][:] = aux_params[name]
#    name = 'PART2_COV_5_bn_moving_mean'
#    print name, aux_params[name].asnumpy()
#    exit()
    return

  def fit(self, train_data, grad_req='write', showperiod=100, whichone=None, logger=None):
    if logger is not None:
      logger.info('Start training with %s', str(self.ctx))

    savefunc = save_checkpoint

    self.get_params(grad_req)
    if whichone is not None:
      self.set_params(whichone)
    self.optimizer = mx.optimizer.create(self.opt_method, rescale_grad=(1.0 / self.batchsize), **self.kwargs)
    self.updater = mx.optimizer.get_updater(self.optimizer)
    self.executor = self.symbol.bind(self.ctx, self.arg_params, args_grad=self.grad_params,
                                     grad_req=grad_req, aux_states=self.aux_params)
    update_dict = self.update_params
#    epoch_end_callback = mx.callback.do_checkpoint(self.prefix)
 
    # begin training
    cost = [] 
    accus = []
    nbatch = 0
    for epoch in range(0, self.num_epoch):
      train_data.reset()
      num_batches = train_data.num_batches
      for databatch in train_data:
        nbatch += 1
        for k, v in databatch.data.items():
#          print k, v.shape
          self.arg_params[k][:] = mx.nd.array(v, self.ctx)
        for k, v in databatch.label.items():
#          print k, v
          self.arg_params[k][:] = mx.nd.array(v, self.ctx)
        output_dict = {name: nd for name, nd in zip(self.symbol.list_outputs(), self.executor.outputs)}
        self.executor.forward(is_train=True)
        self.executor.backward()

#        print '--------------------'
        for key in update_dict:
          arr = self.grad_params[key]
          self.bigbatch_grads[key][:] = self.bigbatch_grads[key] + arr

        if nbatch%self.falsebigbatch==0:
#          print nbatch, self.bigbatchnum
          for key in update_dict:
            arr = self.grad_params[key]
            arr[:] = self.bigbatch_grads[key] / self.falsebigbatch
            self.updater(key, arr, self.arg_params[key])
            self.bigbatch_grads[key][:] = 0

        outval = output_dict['cls_output'].asnumpy()
        label = databatch.label['label']
        cls_predict = np.argmax(outval, axis=1)
        accone = np.mean(cls_predict!=label)
        accus.append(accone)

#        print label
#        print outval
        costone = []
        for oi, ov in enumerate(outval):
#          print np.min(ov), np.max(ov)
          costtmp = 1.0 - ov[label[oi]] 
          costone.append(costtmp)
#        print costone 
        outval = np.mean(costone)
        cost.append(outval)
        lrsch = self.optimizer.lr_scheduler
        step = lrsch.step
        nowlr = lrsch.base_lr
        num_update = nbatch
        if num_update % showperiod == 0:
          print num_update, 'cost:', np.mean(cost), 'lr:', nowlr, num_batches, 'errate_accu:', np.mean(accus)  
          cost = []
          accus = []
          savefunc(self.prefix, epoch%10, self.symbol, self.update_params, self.aux_params)
##          print databatch.label['label'].T










