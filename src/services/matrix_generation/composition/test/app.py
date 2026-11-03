from services.matrix_generation.composition.container import ApplicationContainer
from services.matrix_generation.core.dto import GenerateLinearCombinationsRequest, MatrixParameterDefinition


request = GenerateLinearCombinationsRequest(
    repetitions = 100,
    parameter_definitions=[
        MatrixParameterDefinition('hosts', 'int'),
        MatrixParameterDefinition('interval', 'float'),
        MatrixParameterDefinition('topology', 'str'),
        MatrixParameterDefinition('fix_enabled', 'bool')
    ],
    fixed_params={},
    sweep_params={'interval': ['0.5', '0.7', '0.9'],
                  'hosts': ['50', '70', '90'],
                  'topology': ['star', 'bus'],
                  'fix_enabled': ['true', 'false']
                  },
    matrix_id='1234'
)

container = ApplicationContainer()
container.config.from_dict(
    {
        "aistor": {
            "endpoint": "http://127.0.0.1:9000",
            "access_key": "minio",
            "secret_key": "minio",
            "secure": False,
            "bucket": "tmp",
        },
        "matrix": {"output_prefix": "matrix"},
    }
)
matrix = container.matrix_generation_port().generate_linear_combinations(request)
print(matrix.matrix_url)
