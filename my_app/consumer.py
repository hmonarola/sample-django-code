# consumers.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from .group_manager import group_manager_obj


class FileUploadConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.group_name = self.scope["url_route"]["kwargs"]["group_name"]
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await group_manager_obj.add_group(self.group_name, self.channel_name)
        await self.accept()


    async def disconnect(self, close_code):
        self.group_name = self.scope["url_route"]["kwargs"]["group_name"]
        group_manager_obj.remove_group(self.group_name, self.channel_name)
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def send_content(self, event):
        content = event["content"]
        await self.send(text_data=json.dumps({"content": content}))
