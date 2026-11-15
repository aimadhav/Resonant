"""Import adapter; edit the adjacent all prompts.py file, not this wrapper."""
import importlib.util
from pathlib import Path
_spec=importlib.util.spec_from_file_location('_intervals_agent_prompts',Path(__file__).with_name('all prompts.py'))
_module=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
globals().update({name:value for name,value in vars(_module).items() if not name.startswith('_')})
