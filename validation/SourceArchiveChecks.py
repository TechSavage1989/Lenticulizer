from pathlib import Path
import importlib.util

root=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('package_source',root/'packaging/package_source.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
files={relative.as_posix() for _,relative in module.source_files(root)}
required={
 'README.md','AGENTS.md','DEVELOPMENT_HANDOFF.md','Lenticulizer.csproj','NuGet.Config','global.json',
 'Build_SelfContained.bat','app/Program.cs','app/AppWindow.cs','app/UpdateService.cs','app/UpdateInstaller.cs',
 'app/ReleasePackager.cs','backend/Lenticular-Builder.blend','vendor/FixedRuntime/runtime.zip',
 'blender/Lenticulizer_3D_Blender_Addon_v1.18.43.zip','validation/UpdaterContractChecks.py',
 'validation/RootGuardChecks.py','scripts/check_root.py','scripts/root-allowlist.txt','scripts/restore_fixed_runtime.ps1','.github/workflows/ci.yml','docs/CI.md'
}
missing=sorted(required-files)
assert not missing,'Missing required source-package files: '+', '.join(missing)
for path in files:
 assert '/__pycache__/' not in '/'+path+'/'
 assert not path.endswith(('.pyc','.pyo','.tmp','.part'))
 assert not path.startswith(('bin/','obj/','dist/','release/','.git/'))
 name=Path(path).name
 if path.startswith('validation/heightmap-fixtures/'):
  assert not name.startswith('copy_')
  assert not name.endswith('_copy.tif')
  assert not name.endswith('_csharp.tif')
print(f'PASS: source archive plan contains {len(files)} required/clean files and excludes generated build/test artifacts.')
