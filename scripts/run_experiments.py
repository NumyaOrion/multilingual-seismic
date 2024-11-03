import os
import sys
import subprocess
import time
import toml
import pandas as pd

# TODO
# - Add a file machine.output with information about the machine, its load, free mamory
# - Add MRR@k in the report.tsv

def parse_toml(filename):
    """Parse the TOML configuration file."""
    try:
        return toml.load(filename)
    except Exception as e:
        print(f"Error reading the TOML file: {e}")
        return None
    
def get_git_info(experiment_dir):
    """Get Git repository information and save it to git.output."""
    git_output_file = os.path.join(experiment_dir, "git.output")

    try:
        print("Retrieving Git information...")
        with open(git_output_file, "w") as git_output:
            # Get current branch
            branch_process = subprocess.Popen("git rev-parse --abbrev-ref HEAD", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            branch_name = branch_process.stdout.read().decode().strip()
            branch_process.wait()

            # Get current commit id
            commit_process = subprocess.Popen("git rev-parse HEAD", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            commit_id = commit_process.stdout.read().decode().strip()
            commit_process.wait()

            # Write to git.output
            git_output.write(f"Current Branch: {branch_name}\n")
            git_output.write(f"Commit ID: {commit_id}\n")
            print(f"Current Branch: {branch_name}")
            print(f"Commit ID: {commit_id}")

    except Exception as e:
        print("An error occurred while retrieving Git information:", e)
        sys.exit(1)


def compile_rust_code(experiment_dir):
    """Compile the Rust code and save output."""
    rust_flags = "RUSTFLAGS='-C target-cpu=native' cargo build --release"
    compilation_output_file = os.path.join(experiment_dir, "compiler.output")

    try:
        print("Compiling Rust code...")
        with open(compilation_output_file, "w") as comp_output:
            compile_process = subprocess.Popen(rust_flags, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            for line in iter(compile_process.stdout.readline, b''):
                decoded_line = line.decode()
                print(decoded_line, end='')  # Print each line as it is produced
                comp_output.write(decoded_line)  # Write each line to the output file
            compile_process.stdout.close()
            compile_process.wait()

        if compile_process.returncode != 0:
            print("Rust compilation failed.")
            sys.exit(1)
        print("Rust code compiled successfully.")

    except Exception as e:
        print("An error occurred during Rust compilation:", e)
        sys.exit(1)

def get_index_filename(base_filename, configs):
    """Generate the index filename based on the provided parameters."""
    name = [
        base_filename, 
        'n-postings', configs['indexing_parameters']['n-postings'], 
        'centroid-fraction', configs['indexing_parameters']['centroid-fraction'], 
        'summary-energy', configs['indexing_parameters']['summary-energy'], 
        'knn', configs['indexing_parameters']['knn']
    ]
    
    return "_".join(str(l) for l in name)

def build_index(configs, experiment_dir):
    """Build the index using the provided configuration."""
    input_file =  os.path.join(configs["folder"]["data"], configs["filename"]["dataset"])
    output_file = os.path.join(configs["folder"]["index"], get_index_filename(configs["filename"]["index"], configs))
    print(f"Dataset filename: {input_file }")
    print(f"Index filename: {output_file}")

    command_and_params = [
        "./target/release/build_inverted_index",
        f"--input-file {input_file}",
        f"--output-file {output_file}",
        f"--n-postings {configs['indexing_parameters']['n-postings']}",
        f"--summary-energy {configs['indexing_parameters']['summary-energy']}",
        f"--centroid-fraction {configs['indexing_parameters']['centroid-fraction']}",
        f"--knn {configs['indexing_parameters']['knn']}",
        f"--kmeans-pruning-factor {configs['indexing_parameters']['kmeans-pruning-factor']}",
        f"--kmeans-doc-cut {configs['indexing_parameters']['kmeans-doc-cut']}"
    ]

    if configs['indexing_parameters']['kmeans-approx']:
        command_and_params.append("--kmeans-approx")   

    command = ' '.join(command_and_params)

    # Print the command that will be executed
    print("Building index with command:")
    print(command)

    building_output_file = os.path.join(experiment_dir, "building.output")

    # Build the index and display output in real-time
    print("Building index...")
    with open(building_output_file, "w") as build_output:
        build_process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for line in iter(build_process.stdout.readline, b''):
            decoded_line = line.decode()
            print(decoded_line, end='')  # Print each line as it is produced
            build_output.write(decoded_line)  # Write each line to the output file
        build_process.stdout.close()
        build_process.wait()

    if build_process.returncode != 0:
        print("Index building failed.")
        sys.exit(1)

    print("Index built successfully.")


def compute_accuracy(query_file, gt_file):
    column_names = ["query_id", "doc_id", "rank", "score"]
    gt_pd = pd.read_csv(gt_file, sep='\t', names=column_names)
    res_pd = pd.read_csv(query_file, sep='\t', names=column_names)

    # Group both dataframes by 'query_id' and get unique 'doc_id' sets
    gt_pd_groups = gt_pd.groupby('query_id')['doc_id'].apply(set)
    res_pd_groups = res_pd.groupby('query_id')['doc_id'].apply(set)

    # Compute the intersection size for each query_id in both dataframes
    intersections_size = {
        query_id: len(gt_pd_groups[query_id] & res_pd_groups[query_id]) if query_id in res_pd_groups else 0
        for query_id in gt_pd_groups.index
    }

    # Computes total number of results in the groundtruth
    total_results = len(gt_pd)
    total_intersections = sum(intersections_size.values())
    return total_intersections/total_results

def query_execution(configs, query_config, experiment_dir, subsection_name):
    """Execute a query based on the provided configuration."""
    index_file = os.path.join(configs["folder"]["index"], get_index_filename(configs["filename"]["index"], configs))
    query_file =  os.path.join(configs["folder"]["data"], configs["filename"]["queries"] ) 
    
    output_file = os.path.join(experiment_dir, f"results_{subsection_name}")
    log_output_file =  os.path.join(experiment_dir, f"log_{subsection_name}") 

    command_and_params = [
        "numactl --physcpubind='0-15' --localalloc " if configs['settings']['NUMA'] else "",
        "./target/release/query_inverted_index",
        f"--index-file {index_file}.index.seismic",
        f"-k {configs['settings']['k']}",
        f"--query-file {query_file}",
        f"--query-cut {query_config['query-cut']}",
        f"--heap-factor {query_config['heap-factor']}",
        f"--n-runs {configs['settings']['n-runs']}",
        f"--output-path {output_file}"
    ]

    command = " ".join(command_and_params)

    print(f"Executing query for subsection '{subsection_name}' with command:")
    print(command)

    query_time = 0
    # Run the query and display output in real-time
    print(f"Running query for subsection: {subsection_name}...")
    with open(log_output_file, "w") as log:
        query_process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for line in iter(query_process.stdout.readline, b''):
            decoded_line = line.decode()
            if decoded_line.startswith("Time ") and decoded_line.strip().endswith("microsecs per query"):
                query_time = int(decoded_line.split()[1])
            print(decoded_line, end='')  # Print each line as it is produced
            log.write(decoded_line)  # Write each line to the output file
        query_process.stdout.close()
        query_process.wait()

    if query_process.returncode != 0:
        print(f"Query execution for subsection '{subsection_name}' failed.")
        sys.exit(1)

    print(f"Query for subsection '{subsection_name}' executed successfully.")

    gt_file = os.path.join(configs['folder']['data'], configs['filename']['groundtruth'])

    return query_time, compute_accuracy(output_file, gt_file)

def main(experiment_config_filename):
    """Main function to orchestrate the experiment."""
    config_data = parse_toml(experiment_config_filename)

    if not config_data:
        print("Error: Configuration data is empty.")
        sys.exit(1)

    # Get the experiment name from the configuration
    experiment_name = config_data.get("name")
    print(f"Running experiment: {experiment_name}")

    # Create an experiment folder with date and hour
    from datetime import datetime
    timestamp  = str(datetime.now()).replace(" ", "_")
    experiment_folder = os.path.join(config_data["folder"]["experiment"], f"{experiment_name}_{timestamp}")
    os.makedirs(experiment_folder, exist_ok=True)

    # Store the output of the Rust compilation and index building processes
    get_git_info(experiment_folder)
    compile_rust_code(experiment_folder)
    if config_data['settings']['build']:
        build_index(config_data, experiment_folder)
    else:
        print("Index is already built!")

    # Execute queries for each subsection under [query]
    with open(os.path.join(experiment_folder, "report.tsv"), 'w') as report_file:
        if 'query' in config_data:
            for subsection, query_config in config_data['query'].items():
                query_time, recall = query_execution(config_data, query_config, experiment_folder, subsection)
                report_file.write(f"{subsection}\t{query_time}\t{recall}\n")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run a seismic experiment on a dataset and query it.")
    parser.add_argument("--exp", required=True, help="Path to the experiment configuration TOML file.")
    args = parser.parse_args()

    main(args.exp)
