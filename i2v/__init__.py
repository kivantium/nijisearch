from i2v.base import Illustration2VecBase

caffe_available = False
chainer_available = False
onnx_available = False

try:
    from .onnx_i2v import ONNXI2V, make_i2v_with_onnx
    onnx_available = True
except ImportError:
    pass

try:
    from i2v.caffe_i2v import CaffeI2V, make_i2v_with_caffe
    caffe_available = True
except ImportError:
    pass

try:
    from i2v.chainer_i2v import ChainerI2V, make_i2v_with_chainer
    chainer_available = True
except ImportError:
    pass

if not any([caffe_available, chainer_available, onnx_available]):
    raise ImportError('i2v requires caffe, chainer, or onnx package')
