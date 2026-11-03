def get_columns_names(data):
    """
    It splits names of columns:
    input; output1; output2...
    into:
    (input, [output1, output2...])
    """
    return data.columns[0], data.columns[1:].tolist()
