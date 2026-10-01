import os
from channels.layers import get_channel_layer
import json
import logging

logger = logging.getLogger("apis.views")


class GroupManager:
    def __init__(self):
        self.active_groups = {}

    async def add_group(self, group_name, channel_name):
        if group_name not in self.active_groups:
            self.active_groups[group_name] = set()
        self.active_groups[group_name].add(channel_name)
        with open("group_list.txt", "a") as file:
            file.write(group_name + ",")
        if os.path.exists("transcription_results/{}.txt".format(group_name)):
            channel_layer = get_channel_layer()
            data_to_be_sent = ""
            with open("transcription_results/{}.txt".format(group_name)) as file:
                data_to_be_sent = file.read()
                json_data = json.loads(data_to_be_sent)
                await channel_layer.group_send(
                    group_name,
                    {
                        "type": "send_content",
                        "content": json_data
                    },
                )
                logger.info("transcription result: ", data_to_be_sent)
            os.remove("transcription_results/{}.txt".format(group_name))
        else:
                logger.info("transcription file not generated yet: ")



    def remove_group(self, group_name, channel_name):
        file_content = ''
        with open("group_list.txt", "r+") as f:
            file_content = f.read()
            file_content_list = file_content.split(',')
            file_content_list.remove(group_name)
            write_file_content = ",".join(file_content_list)
            f.seek(0)
            f.truncate()
            f.write(write_file_content)
            
        if group_name in self.active_groups:
            self.active_groups[group_name].discard(channel_name)
            if not self.active_groups[group_name]:
                del self.active_groups[group_name]

    def get_list_of_group_ids(self):
        if os.path.exists("group_list.txt"):
            with open("group_list.txt", "r") as f:
                file_content = f.read()
                file_content_list = file_content.split(',')
                return file_content_list
        else: 
            return []

group_manager_obj = GroupManager()