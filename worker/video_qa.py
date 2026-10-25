"""Killable full-media QA for long jobs; only host-created plans are accepted."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gateway.delivery import safe_job_id, inspect_delivery


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--job-dir',required=True);parser.add_argument('--job-id',required=True)
    args=parser.parse_args();job=Path(args.job_dir)
    safe_job_id(args.job_id)
    if job.is_symlink() or job.name!=args.job_id: raise ValueError('QA任务目录不一致')
    path=job/'validated_video_plan.json'
    if path.is_symlink() or not 0 < path.stat().st_size <= 1024*1024: raise ValueError('QA计划无效')
    spec=json.loads(path.read_text())
    if 'quality' in spec.get('exec_pitch_input',{}):
        from gateway.exec_pitch_delivery import inspect_exec
        from gateway.frame_qa import run_p4
        inspect_exec(args.job_id,spec,job/'staging',_p4_preflight=True)
        report=run_p4(args.job_id,spec,job/'staging')
        if report['delivery_status']!='PASSED':
            raise ValueError('P4交付阻断；逐字不确定项或客户规则缺口保留，见staging/p4_qa.json；不得发布或完成结算')
    manifest=inspect_delivery(args.job_id,'video',spec,job/'staging')
    (job/'qa_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False))


if __name__=='__main__':main()
