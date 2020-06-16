import json
import subprocess
import re

def load_items(path):
  file = open(path, 'r')
  result = json.load(file)
  file.close()
  return result

def assert_item_type(item, _type):
  assert item['sf_type'] == _type

def idify_name(name):
  o = name.lower().strip()
  o = re.sub("[^0-9a-zA-Z]+", "_", o)
  o = re.sub("_+", "_", o)
  o = o.strip('_')

  if o[0].isdigit():
    o = "_" + o

  return o


def map_chart_to_resource_type(chart):
  chart_type = chart['sf_visualizationOptions']['type']
  # Incomplete!
  table = {
    'SingleValue': 'signalfx_single_value_chart',
    'TimeSeriesChart': 'signalfx_time_chart',
    'Heatmap': 'signalfx_heatmap_chart',
    'List': 'signalfx_list_chart',
    'Text': 'signalfx_text_chart'
  }
  return table[chart_type]

def insert_dashboard_attributes(dashboard, dashboard_group_name):
  dashboard['_resource_type'] = 'signalfx_dashboard'
  dashboard['_resource_id'] = f"{dashboard_group_name}--{idify_name(dashboard['sf_dashboard'])}"
  dashboard['_resource_type_id'] = f"{dashboard['_resource_type']}.{dashboard['_resource_id']}"
  dashboard['_file_name'] = f"{dashboard_group_name}_dashboard_group_{idify_name(dashboard['sf_dashboard'])}_dashboard"

def insert_chart_attributes(chart, resource_id, dashboard):
  chart['_resource_type'] = map_chart_to_resource_type(chart)
  chart['_resource_id'] = resource_id
  chart['_resource_type_id'] = f"{chart['_resource_type']}.{chart['_resource_id']}"

  # chart id can only be found in the dashboard :/
  associated_dashboard_widget = list(filter(lambda w: w['options']['chartIndex'] == chart['sf_chartIndex'], dashboard['sf_uiModel']['widgets']))[0]
  
  chart_id = associated_dashboard_widget['options']['chartId']
  chart["_id"] = chart_id

def boilerplate_for_item(item):
  # double curly escapes for f-strings https://stackoverflow.com/a/42521252/10390454
  return f"""
resource "{item['_resource_type']}" "{item['_resource_id']}" {{
}}
"""

def create_boilerplate_for_terraform_import(items, out):
  with open(out, 'w') as boilerplate_file:
    boilerplate_file.write(
"""
provider "signalfx" {
  auth_token = var.signalfx_auth_token
  api_url = var.signalfx_api_url
}

variable "signalfx_auth_token" {
  type = string
}

variable "signalfx_api_url" {
  type = string
}

"""
)
    for item in items:
      boilerplate_file.write(
        boilerplate_for_item(item)
      )

def import_item_state_from_terraform_thunk(item):
  return lambda _: subprocess.Popen(['terraform', 'import', '-no-color', item['_resource_type_id'], item['_id']], stderr=subprocess.PIPE)

def import_item_states(items, max_tries):
  # (item, process, nth_attempt)
  import_state_jobs = []
  for item in items:
    import_state_jobs.append((item, import_item_state_from_terraform_thunk(item), 1))

  while len(import_state_jobs) > 0:
    new_import_state_jobs = []
    for item, process_thunk, nth_attempt in import_state_jobs:
      process = process_thunk(None)
      process.wait()
      
      stderr = process.stderr.read()
      failed = len(stderr) > 0
      if failed:
        print(stderr)
        if nth_attempt >= max_tries:
          raise Exception(f"Error importing state of item {item['_resource_type_id']} from ID {item['_id']}")
        print(f"Failed to import state of item {item['_resource_type_id']} from ID {item['_id']}, retrying...")
        new_import_state_jobs.append((item, import_item_state_from_terraform_thunk(item), nth_attempt + 1))
        continue

      print(f"Successfully imported state of item {item['_resource_type_id']} from ID {item['_id']}")

    import_state_jobs = new_import_state_jobs

  # while len(import_state_jobs) > 0:
  #   new_import_state_jobs = []
  #   for item, process, nth_attempt in import_state_jobs:
  #     if process.poll() is None:
  #       new_import_state_jobs.append((item, process, nth_attempt))
  #       continue
      
  #     stderr = process.stderr.read()
  #     failed = len(stderr) > 0
  #     if failed:
  #       print(stderr)
  #       if nth_attempt >= max_tries:
  #         raise Exception(f"Error importing state of item {item['_resource_type_id']} from ID {item['_id']}")
  #       print(f"Failed to import state of item {item['_resource_type_id']} from ID {item['_id']}, retrying...")
  #       new_import_state_jobs.append((item, process, nth_attempt + 1))
  #       continue
      
  #     print(f"Successfully imported state of item {item['_resource_type_id']} from ID {item['_id']}")

  #   import_state_jobs = new_import_state_jobs

  

def show_state_of_item(item):
  cmd = f"terraform state show {item['_resource_type_id']}"
  print(f"[command] {cmd}")
  p = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE)
  return p.stdout.decode()

def delete_state_files():
  subprocess.call(['rm', '-rf', '.terraform'])
  subprocess.call(['rm', '-f', 'terraform.tfstate'])
  subprocess.call(['rm', '-rf', 'terraform.tfstate.backup'])

def replace_chart_id_with_terraform_identifier(string, item, charts):
  for chart in charts:
    chart_id = chart['_id']
    chart_resource_type_id = chart['_resource_type_id']
    string = string.replace(f'"{chart_id}"', f'{chart_resource_type_id}.id')
  return string

def replace_group_id_with_terraform_id(state_show_output, dashboard, group):
  group_id = group['_id']
  group_resource_type_id = group['_resource_type_id']
  return state_show_output.replace(f'"{group_id}"', f'{group_resource_type_id}.id')

def transform_state_show(state_show_output):
  ansi_escape = re.compile(r'(?:\x1B[@-_]|[\x80-\x9F])[0-?]*[ -/]*[@-~]')
  remove_id_attr = re.compile(r'^ *id *=.*$\n', re.MULTILINE)
  remove_url_attr = re.compile(r'^ *url *=.*$\n', re.MULTILINE)
  eot_start = re.compile(r'<<~EOT', re.MULTILINE)
  eot_end = re.compile(r'EOT', re.MULTILINE)
  remove_comment = re.compile(r'^# .*$\n', re.MULTILINE)

  o = state_show_output
  o = ansi_escape.sub('', o)
  o = remove_id_attr.sub('', o)
  o = remove_url_attr.sub('', o)
  o = eot_start.sub('<<-EOF', o)
  o = eot_end.sub('EOF', o)
  o = remove_comment.sub('', o)

  return o

def write_chart_to_file(chart, f):
  state_show_output = show_state_of_item(chart)  
  state_show_output = transform_state_show(state_show_output)
  f.write(state_show_output)
  f.write('\n')

def write_dashboard_to_file(dashboard, group, charts, f):
  state_show_output = show_state_of_item(dashboard)  
  state_show_output = transform_state_show(state_show_output)
  state_show_output = replace_chart_id_with_terraform_identifier(state_show_output, dashboard, charts)

  if group is not None:
    state_show_output = replace_group_id_with_terraform_id(state_show_output, dashboard, group)

  f.write(state_show_output)
  f.write('\n')

def write_dashboard_group_to_file(dashboard_group, f):
  state_show_output = show_state_of_item(dashboard_group)
  state_show_output = transform_state_show(state_show_output)

  f.write(state_show_output)
  f.write('\n')



def build_mid_to_children_map(items):
  id_to_children_map = {}
  
  for i in range(len(items)):
    item = items[i]
    parent_id = item["marshallMemberOf"][0]
  
    if parent_id not in id_to_children_map:
      id_to_children_map[parent_id] = []
    
    id_to_children_map[parent_id].append(item)

  return id_to_children_map