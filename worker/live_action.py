"""Connect the existing reviewed catalogue / no-key search path to Claude authoring."""
import asyncio
from pathlib import Path

from worker.direct_generation import stop_process


async def prepare_catalog(spec,job,codex_bin,semaphore,req,progress):
    import os
    from worker.scene_assets import load_catalog
    mode=os.getenv('NBPPT_SCENE_SOURCE','catalog')
    if mode=='catalog':
        progress('正在核对已审核实景素材的文件摘要、授权和取景')
        return await asyncio.to_thread(load_catalog,spec['original_prompt_cn'])
    if mode!='search':
        raise ValueError('实景来源配置无效，未替换为图表动画')
    from worker.scene_discovery import discover
    from worker.video_generation import _planner_command,_planner_environment
    async def review_model(directory,instruction,images):
        proc=None
        async with semaphore:
            try:
                with (directory/f'model-{len(list(directory.glob("model-*.log")))}.log').open('xb') as log:
                    proc=await asyncio.create_subprocess_exec(
                        *_planner_command(codex_bin,instruction+'\nDo not delegate or create subagents.',directory,images),
                        cwd=directory,env=_planner_environment(req),stdin=asyncio.subprocess.DEVNULL,
                        stdout=log,stderr=log,start_new_session=True)
                    await asyncio.wait_for(proc.wait(),600)
                    if proc.returncode:
                        raise RuntimeError('素材搜索或画面审核失败，未自动重试')
            finally:
                # The outer generator cancels and awaits this task before refunding.
                await stop_process(proc)
    return await discover(spec,job/'discovery',review_model,progress)
