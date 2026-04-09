import json

def count_main_objects(json_file):
    """
    Counts the number of main objects in a JSON file.
    
    Args:
    json_file (str): Path to the JSON file.
    
    Returns:
    int: Number of main objects.
    """
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    return len(data)


def split_json_file(json_file, num_files):
    """
    Splits a JSON file into smaller files.
    
    Args:
    json_file (str): Path to the JSON file.
    num_files (int): Number of files to split into.
    
    Returns:
    None
    """
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Calculate the number of objects per file
    num_objects_per_file = len(data) // num_files
    
    # Calculate the remaining objects
    remaining_objects = len(data) % num_files
    
    # Initialize the object index
    obj_index = 0
    
    for i in range(num_files):
        # Calculate the number of objects for this file
        num_objects = num_objects_per_file + (1 if i < remaining_objects else 0)
        
        # Create a new file
        with open(f'{json_file[:-5]}_{i+1}.json', 'w', encoding='utf-8') as new_f:
            json.dump(data[obj_index:obj_index+num_objects], new_f, indent=4, ensure_ascii=False)
        
        # Update the object index
        obj_index += num_objects


if __name__ == "__main__":
    json_file = 'lane_lexicon_3.json'  # replace with your JSON file
    num_files = 3  # number of files to split into
    
    # Count main objects
    num_objects = count_main_objects(json_file)
    print(f"Number of main objects: {num_objects}")
    
    # Split JSON file
    split_json_file(json_file, num_files)
    print(f"JSON file split into {num_files} files.")