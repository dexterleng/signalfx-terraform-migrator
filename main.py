import json
import subprocess
import re

signalfx_export_path = './kcp_group.json'
DASHBOARD_GROUP_NAME='kcp_group'

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

def insert_dashboard_attributes(dashboard):
  dashboard['_resource_type'] = 'signalfx_dashboard'
  dashboard['_resource_id'] = idify_name(dashboard['sf_dashboard'])
  dashboard['_resource_type_id'] = f"{dashboard['_resource_type']}.{dashboard['_resource_id']}"
  dashboard['_file_name'] = f"{DASHBOARD_GROUP_NAME}_dashboard_group_{dashboard['_resource_id']}_dashboard"

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

def write_item_state_to_file(item, charts, f):
  ansi_escape = re.compile(r'(?:\x1B[@-_]|[\x80-\x9F])[0-?]*[ -/]*[@-~]')
  remove_id_attr = re.compile(r'^ *id *=.*$\n', re.MULTILINE)
  remove_url_attr = re.compile(r'^ *url *=.*$\n', re.MULTILINE)
  eot_start = re.compile(r'<<~EOT', re.MULTILINE)
  eot_end = re.compile(r'EOT', re.MULTILINE)
  remove_comment = re.compile(r'^# .*$\n', re.MULTILINE)

  o = show_state_of_item(item)
  o = ansi_escape.sub('', o)
  o = remove_id_attr.sub('', o)
  o = remove_url_attr.sub('', o)
  o = eot_start.sub('<<-EOF', o)
  o = eot_end.sub('EOF', o)
  o = remove_comment.sub('', o)
  o = replace_chart_id_with_terraform_identifier(o, item, charts)

  f.write(o)
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

def main():
  delete_state_files()

  items = list(filter(lambda i: 'sf_type' in i and i['sf_type'] in ['Page', 'Dashboard', 'Chart'] , load_items(signalfx_export_path)))

  dashboard_group = list(filter(lambda i: i.get('sf_type') == 'Page', items))[0]
  all_dashboards = list(filter(lambda i: i.get('sf_type') == 'Dashboard', items))
  all_charts = list(filter(lambda i: i.get('sf_type') == 'Chart', items))

  marshall_id_to_children_map = build_mid_to_children_map(all_dashboards + all_charts)

  # set dashboard attributes
  for dashboard in all_dashboards:
    dashboard_mid = dashboard['marshallId']
    one_chart = marshall_id_to_children_map[dashboard_mid][0]

    dashboard_id = one_chart['sf_dashboardId']
    dashboard['_id'] = dashboard_id

    insert_dashboard_attributes(dashboard)

  # set chart attributes
  chart_resource_id_count = {}
  for dashboard in all_dashboards:
    dashboard_mid = dashboard['marshallId']

    for chart in marshall_id_to_children_map[dashboard_mid]:
      # prevent chart id collision by adding _{nth_appearance} suffix to resource_id
      chart_name = idify_name(f"{DASHBOARD_GROUP_NAME}_dashboard_group_{dashboard['_resource_id']}_dashboard_{chart['sf_chart']}")
      if chart_name not in chart_resource_id_count:
        chart_resource_id_count[chart_name] = 0
      chart_resource_id_count[chart_name] += 1

      chart_resource_id = f'{chart_name}_{chart_resource_id_count[chart_name]}'
      if chart_resource_id_count[chart_name] == 1:
        chart_resource_id = chart_name 

      insert_chart_attributes(chart, chart_resource_id, dashboard)

  # create boilerplate file that is required to run `terraform import`
  create_boilerplate_for_terraform_import(all_dashboards + all_charts, './boilerplate.tf')

  subprocess.call(['terraform', 'init'])

  # import dashboards and chart state
  import_item_states(all_dashboards + all_charts, 3)

  # write state config to file
  subprocess.run(['mkdir', '-p', 'output/'])

  for i in range(len(all_dashboards)):
    dashboard = all_dashboards[i]
    dashboard_mid = dashboard['marshallId']
    charts = marshall_id_to_children_map[dashboard_mid]

    with open(f"output/{dashboard['_file_name']}.tf", 'w') as output_file:
      write_item_state_to_file(dashboard, charts, output_file)
      for chart in charts:
        # no need to replace non-exist chart_id attribute
        write_item_state_to_file(chart, [], output_file)

  delete_state_files()

main()
