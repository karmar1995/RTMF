import numpy as np
import pandas as pd
from sysidentpy.model_structure_selection import FROLS
from sysidentpy.basis_function import Polynomial
from sysidentpy.parameter_estimation import LeastSquares

def test_nar():
    # Dummy data: constant values (known to cause SVD issues often)
    y = np.array([1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]).reshape(-1, 1)
    
    basis_function = Polynomial(degree=2)
    model = FROLS(
        order_selection=True,
        ylag=2,
        estimator=LeastSquares(),
        basis_function=basis_function,
        model_type="NAR"
    )
    
    try:
        model.fit(X=None, y=y)
        print("Fit successful")
    except Exception as e:
        print(f"Fit failed: {e}")

if __name__ == "__main__":
    test_nar()
