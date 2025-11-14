from prometheus_api_client import PrometheusConnect
from prometheus_api_client.utils import parse_datetime
from datetime import timedelta
import time
import subprocess
import math

prom = PrometheusConnect(url ="http://k3s.example:8080", disable_ssl=True)

start_time = parse_datetime("1m")
end_time = parse_datetime("now")
chunk_size = timedelta(minutes=1)

while True:
    #pods_pending = prom.custom_query(query='sum(kube_pod_status_phase{phase="Pending", namespace="default"})')
    #pods_pending = pods_pending[0]['value'][1]

    #define localização do manifesto terraform
    tf_file_location = "/home/ubuntu/terraform_worker_node"

    #pega o número atual de nós do cluster
    count_string = subprocess.check_output(f"grep -oP 'count=\K\d+' {tf_file_location}/main.tf", shell=True)
    count_string = int(count_string)

    #Uso de CPU dos nós:
    cpu_usage = prom.custom_query(query="avg(1 - avg(irate(node_cpu_seconds_total{mode='idle'}[1m])) by (instance)) * 100")

    if(cpu_usage!=[]):
        cpu_usage = float(cpu_usage[0]['value'][1])
    else:
        cpu_usage = 0.0

    #Média de uso de memória dos nós
    mem_usage = prom.custom_query(query="100 * (1 - ((avg(avg_over_time(node_memory_MemFree_bytes[1m])) + avg(avg_over_time(node_memory_Cached_bytes[1m])) + avg(avg_over_time(node_memory_Buffers_bytes[1m]))) / avg(avg_over_time(node_memory_MemTotal_bytes[1m]))))")

    if(mem_usage!=[]):
        mem_usage = float(mem_usage[0]['value'][1])
    else:
        mem_usage = 0.0

    list = [cpu_usage, mem_usage]
    desiredMetricValue = 80

    desiredReplicas_list = []
    for el in list: 
        currentMetricValue = el
        desiredReplicas = math.ceil(count_string * (currentMetricValue / desiredMetricValue))

        if(desiredReplicas<2):
            desiredReplicas = 2

        desiredReplicas_list.append(desiredReplicas)
            
    desiredReplicas = max(desiredReplicas_list)

    if desiredReplicas != count_string:
        print("Escale!")

        if(desiredReplicas < count_string):
            time.sleep(15)

        #Soma o valor necessário de nós no arquivo, substituindo a string
        sub_string = subprocess.check_output(f"sed -i 's/count=[0-9]\+/count={str(desiredReplicas)}/' /{tf_file_location}/main.tf", shell=True)

        init = subprocess.check_output('terraform -chdir=' + tf_file_location + ' init', shell=True)

        #Aplica o código terraform para criar a VM
        create_vm = subprocess.check_output('terraform -chdir=' + tf_file_location + ' apply -auto-approve', shell=True)

        #Aplica novamente para por a VM no LoadBalancer
        edit_elb = subprocess.check_output('terraform -chdir=' + tf_file_location + ' apply -auto-approve', shell=True)

        #formata a saída dos comandos
        create_vm = create_vm.decode("utf-8")
        edit_elb = edit_elb.decode("utf-8")
        print(create_vm)
        print(edit_elb)
    else:
        print("Not scaling")

    time.sleep(10)
    
