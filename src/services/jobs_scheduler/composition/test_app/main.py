from __future__ import annotations

import time
from services.jobs_scheduler.composition.root import create_container

matrix_uri = 's3://tmp/matrix/dd9eaaf9.txt'
simulator_uri = 'docker://registry.local/simulators/fluid_flow_7:v-1.0.0'
combinations = 2


container = create_container()
service = container.jobs_scheduler_service()

jobs = service.list_jobs()
print(jobs)

batchInfo = service.submit_simulation_batch(
    matrix_uri=matrix_uri,
    simulator_uri=simulator_uri,
    combinations=combinations,
    simulator_id='7'
)

job_id = batchInfo.job_id
status = service.get_job(job_id).status
while status != 'successful' and status != 'failed':
    print(f"Job {job_id} status is {status}")
    sub_jobs = service.get_job_sub_jobs(job_id=job_id)
    for sub_job_info in sub_jobs:
        print(f"Subjob {sub_job_info.job_id}.{sub_job_info.sub_job_id} status is {sub_job_info.status}")
    status = service.get_job(job_id).status

print(f"Job {job_id} status is {status}")
sub_jobs = service.get_job_sub_jobs(job_id=job_id)
for sub_job_info in sub_jobs:
    print(f"Subjob {sub_job_info.job_id}.{sub_job_info.sub_job_id} status is {sub_job_info.status}")
    print(f"Std out: {service.get_sub_job_stdout(sub_job_info.job_id, sub_job_info.sub_job_id)}")
    print(f"Std err: {service.get_sub_job_stderr(sub_job_info.job_id, sub_job_info.sub_job_id)}")
status = service.get_job(job_id).status

for i in range(0, 5):
    print(f"Waiting for job to be stored... {i}")
    time.sleep(2)
