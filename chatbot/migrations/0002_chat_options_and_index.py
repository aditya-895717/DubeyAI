from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("chatbot", "0001_initial")]

    operations = [
        migrations.AlterModelOptions(
            name="chat",
            options={"ordering": ["created_at"]},
        ),
        migrations.AddIndex(
            model_name="chat",
            index=models.Index(
                fields=["user", "-created_at"],
                name="chatbot_cha_user_id_23596f_idx",
            ),
        ),
        migrations.AlterField(
            model_name="chat",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="chats",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
