using System.Text.Json.Nodes;

namespace Chao2Harvester;

public partial class MainWindow
{
    private static void MigrateCocoonOptions(JsonNode? node)
    {
        if(node is not JsonObject options)return;
        options.Remove("max_runs");
        int previous=options["reserve_spikes"]?.GetValue<int>() ?? 0;
        options["reserve_spikes_enabled"] ??= JsonValue.Create(previous>0);
        if(previous==0)options["reserve_spikes"]=1;
        if(options["targets"] is JsonArray targets)
            foreach(var row in targets.OfType<JsonObject>())row.Remove("limit");
    }

    private static void MigrateResourceLimits(JsonObject saved)
    {
        saved.Remove("max_battles");
        MigrateCocoonOptions(saved["task_options"]?["cocoon"]);
        if(saved["task_queue"] is JsonArray queue)
            foreach(var row in queue.OfType<JsonObject>())
                if(row["key"]?.ToString()=="cocoon")MigrateCocoonOptions(row["options"]);
        if(saved["task_templates"] is JsonArray templates)
            foreach(var row in templates.OfType<JsonObject>())
                if(row["settings"] is JsonObject snapshot)MigrateResourceLimits(snapshot);
    }
}
