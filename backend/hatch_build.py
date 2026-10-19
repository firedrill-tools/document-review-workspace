"""Include only reviewed optional integration source in the backend sdist."""
from pathlib import Path
from hatchling.builders.hooks.plugin.interface import BuildHookInterface
class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        if self.target_name != 'sdist': return
        root = Path(self.root)
        integration = root/'firedrill' if (root/'firedrill').is_dir() else root.parent/'firedrill'
        for name in ('.gitignore', 'README.md', 'adapter-runtime.mjs', 'adapter.test.mjs', 'package.json', 'package-lock.json', 'request.py', 'scenario.json', 'simulate.mjs', 'target.mjs'):
            source = integration/name
            if source.is_file(): build_data['force_include'][str(source)] = 'firedrill/'+name
