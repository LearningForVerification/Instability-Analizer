import csv
import logging
import time

from InstabilityInspector.pynever import utilities
from InstabilityInspector.pynever.networks import SequentialNetwork, NeuralNetwork
from InstabilityInspector.pynever.strategies import verification, conversion
from InstabilityInspector.pynever.tensor import Tensor

BENCHMARKS_PATH = '../../../examples/benchmarks'

logger_stream = logging.getLogger("pynever.strategies.verification")
logger_stream.addHandler(logging.StreamHandler())
logger_stream.setLevel(logging.INFO)

logger_file = logging.getLogger("log_file")
logger_file.addHandler(logging.FileHandler('logs/experiments.csv'))
logger_file.setLevel(logging.INFO)


def format_csv(answer: list, nn: NeuralNetwork, prop_name: str) -> str:
    # If answer is False without counterexample -> timeout
    if len(answer) == 1:
        if answer[0]:
            with open(f'logs/{nn.identifier}-{prop_name}_result.txt', 'w') as out:
                out.write('unsat')

            return 'Verified'
        else:
            with open(f'logs/{nn.identifier}-{prop_name}_result.txt', 'w') as out:
                out.write('unknown')

            return 'Unknown'

    else:
        print_cex_file(answer[1], nn, prop_name)

        fancy_cex = '['
        for component in answer[1]:
            fancy_cex += str(float(component[0]))
            fancy_cex += ' '
        fancy_cex = fancy_cex[:-1]
        fancy_cex += ']'

        return f'Falsified,{fancy_cex}'


def print_cex_file(cex_input: Tensor, net: NeuralNetwork, p_name: str):
    """
    sat (not verified) + cex input
    """

    unsafe_out = utilities.execute_network(net, cex_input)
    text = ''
    for i in range(len(cex_input)):
        text += f'(X_{i} {cex_input[i]})\n'

    for j in range(len(unsafe_out)):
        text += f'(Y_{j} {unsafe_out[j]})\n'
    text = text.replace('[', '').replace(']', '')[:-1]

    with open(f'logs/{net.identifier}-{p_name}_result.txt', 'w') as out:
        out.write('sat\n')
        out.write(f'({text})')


def launch_instances(instances_file: str):
    logger_file.info('Instance,Time,Result,Counterexample')
    folder = instances_file.replace(instances_file.split('/')[-1], '')
    with open(instances_file, 'r') as f:
        csv_reader = csv.reader(f)

        for instance in csv_reader:

            network_path = f'{folder}/{instance[0]}'
            ver_strategy = verification.SearchVerification()
            onnx_net = conversion.load_network_path(network_path)
            if isinstance(onnx_net, conversion.ONNXNetwork):
                net = conversion.ONNXConverter().to_neural_network(onnx_net)

                if isinstance(net, SequentialNetwork):
                    prop = verification.NeVerProperty()
                    prop.from_smt_file(f'{folder}/{instance[1]}')

                    p_name = instance[1].split("/")[-1]
                    inst_name = f'{instance[0].split("/")[-1]} - {p_name}'

                    logger_stream.info(f'Instance: {inst_name}')

                    start_time = time.perf_counter()
                    result = ver_strategy.verify(net, prop)
                    lap = time.perf_counter() - start_time

                    logger_stream.info(f'{result} - {lap}')
                    logger_file.info(f'{inst_name},{lap},{format_csv(result, net, p_name)}')


if __name__ == '__main__':
    launch_instances(f'{BENCHMARKS_PATH}/RL/instances.csv')
