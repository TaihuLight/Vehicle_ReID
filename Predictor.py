import logging
import mxnet as mx
import numpy as np
import cPickle
import os


class CarReID_Predictor(object):
  def __init__(self, prefix='', symbol=None, ctx=None, data_shape=None):
    self.prefix = prefix
    self.symbol = symbol
    self.ctx = ctx
    if self.ctx is None:
      self.ctx = mx.cpu() 
    self.data_shape = data_shape
    self.batchsize = data_shape[0]
    self.arg_params = None
    self.aux_params = None
    self.executor = None

  def get_params(self):
    arg_names = self.symbol.list_arguments()
    arg_shapes, _, aux_shapes = \
                self.symbol.infer_shape(part1_data=self.data_shape,
                                        part2_data=self.data_shape)

    self.arg_params = {}
    for name, shape in zip(arg_names, arg_shapes):
      self.arg_params[name] = mx.nd.zeros(shape, self.ctx)

    aux_names = self.symbol.list_auxiliary_states()
    self.aux_params = {k: mx.nd.zeros(s, self.ctx) for k, s in zip(aux_names, aux_shapes)}

  def set_params(self, whichone):
    logging.info('loading checkpoint from %s-->%d...', self.prefix, whichone)
    loadfunc = mx.model.load_checkpoint
    _, update_params, aux_params = loadfunc(self.prefix, whichone)
    for name in update_params:
      self.arg_params[name][:] = update_params[name]
#      print update_params[name].asnumpy()
    for name in aux_params:
      self.aux_params[name][:] = aux_params[name]   
#      print name, aux_params[name].asnumpy()
#    exit()
    return

  def predict(self, data_query, data_set, whichone=None, logger=None):
    if logger is not None:
      logger.info('Start testing with %s', str(self.ctx))

    self.get_params()
    if whichone is not None:
      self.set_params(whichone)
    self.executor = self.symbol.bind(ctx=self.ctx, args=self.arg_params, grad_req='null', aux_states=self.aux_params)
#    print self.executor.arg_dict['part1_data'], self.executor.arg_dict['part2_data']
#    print self.arg_params['part1_data'], self.arg_params['part2_data']
#    for av in self.aux_params:
#      print av, self.aux_params[av].asnumpy()
#    exit()
    # begin training
    data_query.reset()
    for dquery in data_query:
#      datainfo1 = dquery['sons'][0]
      id1 = dquery['id']
      for datainfo1 in dquery['sons']:
        data1 = datainfo1['data'].reshape((1,)+datainfo1['data'].shape)
        cmpfile = open('Result/cmp=%s=%s.list'%(id1, datainfo1['name']), 'w')
  #      d1s = np.mean(data1)
  #      print data1.shape, self.arg_params['part1_data'].asnumpy().shape
        self.arg_params['part1_data'][:] = mx.nd.array(data1, self.ctx)
        data_set.reset()
        for dset in data_set:
          id2 = dset['id']
          for datainfo2 in dset['sons']:
            data2 = datainfo2['data'].reshape((1,)+datainfo2['data'].shape)
    #        d2s = np.mean(data2)
            self.arg_params['part2_data'][:] = mx.nd.array(data2, self.ctx)
    
            self.executor.forward(is_train=False)
            cmp_score = self.executor.outputs[0].asnumpy()[0, 0]
            cmpfile.write('%s,%s,%f\n'%(id2, datainfo2['name'], cmp_score)) 
            cmpfile.flush()
    #        print 'query:%s,%.3f,%d; dset:%s,%.3f,%d; %.3f'%(id1, d1s, data_query.cur_idx, id2, d2s, data_set.cur_idx, cmp_score)
            print 'query:%s,%d; dset:%s,%d; %.3f'%(id1, data_query.cur_idx, id2, data_set.cur_idx, cmp_score)
        cmpfile.close()
#       exit()


class CarReID_Feature_Predictor(object):
  def __init__(self, prefix='', symbol=None, ctx=None, data_shape=None):
    self.prefix = prefix
    self.symbol = symbol
    self.ctx = ctx
    if self.ctx is None:
      self.ctx = mx.cpu() 
    self.data_shape = data_shape
    self.batchsize = data_shape[0]
    self.arg_params = None
    self.aux_params = None
    self.executor = None

  def get_params(self):
    arg_names = self.symbol.list_arguments()
    arg_shapes, _, aux_shapes = \
                self.symbol.infer_shape(part1_data=self.data_shape)

    self.arg_params = {}
    for name, shape in zip(arg_names, arg_shapes):
      self.arg_params[name] = mx.nd.zeros(shape, self.ctx)

    aux_names = self.symbol.list_auxiliary_states()
    self.aux_params = {k: mx.nd.zeros(s, self.ctx) for k, s in zip(aux_names, aux_shapes)}

  def set_params(self, whichone):
    logging.info('loading checkpoint from %s-->%d...', self.prefix, whichone)
    loadfunc = mx.model.load_checkpoint
    _, update_params, aux_params = loadfunc(self.prefix, whichone)
    for name in self.arg_params:
      if name.endswith('weight') or name.endswith('bias') or name.endswith('gamma') or name.endswith('beta'):
        self.arg_params[name][:] = update_params[name]
#      print update_params[name].asnumpy()
    for name in self.aux_params:
      if name.endswith('moving_var') or name.endswith('moving_mean'):
        self.aux_params[name][:] = aux_params[name]   
#        print name, aux_params[name].asnumpy()
#    exit()
    return

  def predict(self, data_set, savepath, whichone=None, logger=None):
    if logger is not None:
      logger.info('Start testing with %s', str(self.ctx))

    self.get_params()
    if whichone is not None:
      self.set_params(whichone)
    self.executor = self.symbol.bind(ctx=self.ctx, args=self.arg_params, grad_req='null', aux_states=self.aux_params)

    # begin training
    data_set.reset()
    for dquery in data_set:
      id1 = dquery['id']
      for datainfo1 in dquery['sons']:
        data1 = datainfo1['data'].reshape((1,)+datainfo1['data'].shape)
        self.arg_params['part1_data'][:] = mx.nd.array(data1, self.ctx)
        self.executor.forward(is_train=False)
        feature = self.executor.outputs[0].asnumpy()
        idfolder = savepath + '/' + id1
        if not os.path.exists(idfolder):
          os.makedirs(idfolder)
        featfn = idfolder + '/' + datainfo1['name'] + '.bin'
        cPickle.dump(feature, open(featfn, 'wb')) 
        print 'saved feature:%d/%d, %s'%(data_set.cur_idx, data_set.datalen, featfn)


class CarReID_Compare_Predictor(object):
  def __init__(self, prefix='', symbol=None, ctx=None, data_shape=None):
    self.prefix = prefix
    self.symbol = symbol
    self.ctx = ctx
    if self.ctx is None:
      self.ctx = mx.cpu() 
    self.data_shape = data_shape
    self.batchsize = data_shape[0]
    self.arg_params = None
    self.aux_params = None
    self.executor = None

  def get_params(self):
    arg_names = self.symbol.list_arguments()
    arg_shapes, _, aux_shapes = \
                self.symbol.infer_shape(feature1_data=self.data_shape,
                                        feature2_data=self.data_shape)

    self.arg_params = {}
    for name, shape in zip(arg_names, arg_shapes):
      self.arg_params[name] = mx.nd.zeros(shape, self.ctx)

    aux_names = self.symbol.list_auxiliary_states()
    self.aux_params = {k: mx.nd.zeros(s, self.ctx) for k, s in zip(aux_names, aux_shapes)}

  def set_params(self, whichone):
    logging.info('loading checkpoint from %s-->%d...', self.prefix, whichone)
    loadfunc = mx.model.load_checkpoint
    _, update_params, aux_params = loadfunc(self.prefix, whichone)
    for name in self.arg_params:
      if name.endswith('weight') or name.endswith('bias') or name.endswith('gamma') or name.endswith('beta'):
        self.arg_params[name][:] = update_params[name]
#      print update_params[name].asnumpy()
    for name in self.aux_params:
      if name.endswith('moving_var') or name.endswith('moving_mean'):
        self.aux_params[name][:] = aux_params[name]   
#        print name, aux_params[name].asnumpy()
#    exit()
    return

  def predict(self, data_query, data_set, whichone=None, logger=None):
    if logger is not None:
      logger.info('Start Comparing with %s', str(self.ctx))

    self.get_params()
    if whichone is not None:
      self.set_params(whichone)
    self.executor = self.symbol.bind(ctx=self.ctx, args=self.arg_params, grad_req='null', aux_states=self.aux_params)

    data_query.reset()
    for dquery in data_query:
      id1 = dquery['id']
      for datainfo1 in dquery['sons']:
        data1 = datainfo1['data'].reshape((1,)+datainfo1['data'].shape)
        cmpfile = open('Result/cmp=%s=%s.list'%(id1, datainfo1['name']), 'w')
        self.arg_params['feature1_data'][:] = mx.nd.array(data1, self.ctx)
        data_set.reset()
        for dset in data_set:
          id2 = dset['id']
          for datainfo2 in dset['sons']:
            data2 = datainfo2['data'].reshape((1,)+datainfo2['data'].shape)
            self.arg_params['feature2_data'][:] = mx.nd.array(data2, self.ctx)
    
            self.executor.forward(is_train=False)
            cmp_score = self.executor.outputs[0].asnumpy()[0, 0]
            cmpfile.write('%s,%s,%f\n'%(id2, datainfo2['name'], cmp_score)) 
            cmpfile.flush()
            print 'query:%s,%d; dset:%s,%d; %.3f'%(id1, data_query.cur_idx, id2, data_set.cur_idx, cmp_score)
        cmpfile.close()

