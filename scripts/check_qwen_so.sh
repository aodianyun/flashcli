
/usr/bin/python3.10 -c "
import importlib.util, glob
so = glob.glob('bundles/qwen_nvfp4/lib/flash_rt_kernels-*-py310.so')[0]
spec = importlib.util.spec_from_file_location('flash_rt_kernels', so)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
print('py310 OK', so)
"

/usr/bin/python3.11 -c "
import importlib.util, glob
so = glob.glob('bundles/qwen_nvfp4/lib/flash_rt_kernels-*-py311.so')[0]
spec = importlib.util.spec_from_file_location('flash_rt_kernels', so)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
print('py311 OK', so)
"

/usr/bin/python3.12 -c "
import importlib.util, glob
so = glob.glob('bundles/qwen_nvfp4/lib/flash_rt_kernels-*-py312.so')[0]
spec = importlib.util.spec_from_file_location('flash_rt_kernels', so)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
print('py312 OK', so)
"