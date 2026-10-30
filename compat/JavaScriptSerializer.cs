using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text.Json;
using System.Text.Encodings.Web;

// Keep the established project API and its object[]/dictionary representation
// while using the JSON implementation supplied by the bundled .NET runtime.
// No System.Web.Extensions or .NET Framework installation is required.
namespace System.Web.Script.Serialization
{
    internal sealed class JavaScriptSerializer
    {
        public int MaxJsonLength { get; set; } = 16 * 1024 * 1024;
        public int RecursionLimit { get; set; } = 64;

        public object DeserializeObject(string json)
        {
            if (json == null) throw new ArgumentNullException("json");
            if (json.Length > MaxJsonLength) throw new ArgumentException("The project JSON is too large.");
            try
            {
                using (var document = JsonDocument.Parse(json, new JsonDocumentOptions { MaxDepth = RecursionLimit }))
                    return ConvertElement(document.RootElement);
            }
            catch (JsonException error) { throw new ArgumentException("Invalid project JSON.", error); }
        }

        static object ConvertElement(JsonElement value)
        {
            switch (value.ValueKind)
            {
                case JsonValueKind.Object:
                    var map = new Dictionary<string, object>(StringComparer.Ordinal);
                    foreach (var item in value.EnumerateObject()) map[item.Name] = ConvertElement(item.Value);
                    return map;
                case JsonValueKind.Array:
                    var array = new List<object>();
                    foreach (var item in value.EnumerateArray()) array.Add(ConvertElement(item));
                    return array.ToArray();
                case JsonValueKind.String: return value.GetString();
                case JsonValueKind.True: return true;
                case JsonValueKind.False: return false;
                case JsonValueKind.Null: return null;
                case JsonValueKind.Number:
                    string text = value.GetRawText();
                    int small; long large; decimal precise;
                    if (int.TryParse(text, NumberStyles.Integer, CultureInfo.InvariantCulture, out small)) return small;
                    if (long.TryParse(text, NumberStyles.Integer, CultureInfo.InvariantCulture, out large)) return large;
                    if (text.IndexOf('e') < 0 && text.IndexOf('E') < 0 && decimal.TryParse(text, NumberStyles.Number, CultureInfo.InvariantCulture, out precise)) return precise;
                    double number = value.GetDouble();
                    if (double.IsInfinity(number) || double.IsNaN(number)) throw new ArgumentException("Non-finite project number.");
                    return number;
                default: throw new ArgumentException("Unsupported project JSON value.");
            }
        }

        public string Serialize(object value)
        {
            string json = JsonSerializer.Serialize(value, new JsonSerializerOptions
            {
                MaxDepth = RecursionLimit, IncludeFields = true,
                Encoder = JavaScriptEncoder.Default
            });
            if (json.Length > MaxJsonLength) throw new ArgumentException("The project JSON is too large.");
            return json;
        }
    }
}
