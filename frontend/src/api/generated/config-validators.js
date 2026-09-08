// Generated from production response schemas. Run npm run contracts:generate.
"use strict";
export const validateConfigResponse = validate53;
const schema20 = {"properties":{"data":{"anyOf":[{"$ref":"#/components/schemas/SystemConfigModel"},{"type":"null"}],"default":null},"message":{"title":"Message","type":"string"},"success":{"title":"Success","type":"boolean"}},"required":["success","message","data"],"title":"ConfigResponse","type":"object"};
const schema21 = {"properties":{"agent":{"$ref":"#/components/schemas/AgentConfigModel"},"diagnostics":{"$ref":"#/components/schemas/DiagnosticsConfigModel"},"llm":{"$ref":"#/components/schemas/LLMConfigModel"},"memory":{"$ref":"#/components/schemas/MemoryConfigModel"},"network":{"$ref":"#/components/schemas/NetworkProxyConfigModel"},"personality":{"$ref":"#/components/schemas/PersonalityConfigModel"},"personalitySettings":{"$ref":"#/components/schemas/PersonalitySettingsModel"},"preferences":{"$ref":"#/components/schemas/UserPreferencesModel"},"revision":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"description":"Snapshot revision required for general configuration writes.","title":"Revision"},"skills":{"items":{"type":"string"},"title":"Skills","type":"array"},"timeline":{"$ref":"#/components/schemas/TimelineConfigModel"}},"required":["revision","agent","llm","memory","preferences","network","diagnostics","personality","personalitySettings","skills","timeline"],"title":"SystemConfigModel","type":"object"};
const schema22 = {"properties":{"description":{"anyOf":[{"type":"string"},{"type":"null"}],"default":"Magi AI Agent Framework","title":"Description"},"name":{"default":"magi-agent","title":"Name","type":"string"}},"required":["name","description"],"title":"AgentConfigModel","type":"object"};

function validate55(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate55.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((data.name === undefined) && (missing0 = "name")) || ((data.description === undefined) && (missing0 = "description"))){
validate55.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.description !== undefined){
let data0 = data.description;
const _errs1 = errors;
const _errs2 = errors;
let valid1 = false;
const _errs3 = errors;
if(typeof data0 !== "string"){
const err0 = {instancePath:instancePath+"/description",schemaPath:"#/properties/description/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs3 === errors;
valid1 = valid1 || _valid0;
const _errs5 = errors;
if(data0 !== null){
const err1 = {instancePath:instancePath+"/description",schemaPath:"#/properties/description/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs5 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/description",schemaPath:"#/properties/description/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate55.errors = vErrors;
return false;
}
else {
errors = _errs2;
if(vErrors !== null){
if(_errs2){
vErrors.length = _errs2;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.name !== undefined){
const _errs7 = errors;
if(typeof data.name !== "string"){
validate55.errors = [{instancePath:instancePath+"/name",schemaPath:"#/properties/name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
}
}
}
else {
validate55.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate55.errors = vErrors;
return errors === 0;
}
validate55.evaluated = {"props":{"description":true,"name":true},"dynamicProps":false,"dynamicItems":false};

const schema23 = {"properties":{"full_content_logging_enabled":{"default":true,"title":"Full Content Logging Enabled","type":"boolean"}},"required":["full_content_logging_enabled"],"title":"DiagnosticsConfigModel","type":"object"};

function validate57(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate57.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((data.full_content_logging_enabled === undefined) && (missing0 = "full_content_logging_enabled")){
validate57.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.full_content_logging_enabled !== undefined){
if(typeof data.full_content_logging_enabled !== "boolean"){
validate57.errors = [{instancePath:instancePath+"/full_content_logging_enabled",schemaPath:"#/properties/full_content_logging_enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
}
}
}
else {
validate57.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate57.errors = vErrors;
return errors === 0;
}
validate57.evaluated = {"props":{"full_content_logging_enabled":true},"dynamicProps":false,"dynamicItems":false};

const schema24 = {"properties":{"model_runtime_overrides":{"additionalProperties":{"$ref":"#/components/schemas/LLMConcurrencyOverrideSettings"},"title":"Model Runtime Overrides","type":"object"},"providers":{"additionalProperties":{"$ref":"#/components/schemas/LLMProviderConfigModel"},"title":"Providers","type":"object"},"selections":{"additionalProperties":{"$ref":"#/components/schemas/LLMSelectionConfigModel"},"title":"Selections","type":"object"}},"required":["providers","selections","model_runtime_overrides"],"title":"LLMConfigModel","type":"object"};
const schema25 = {"description":"Shared concurrency override for a concrete provider-model family.","properties":{"max_concurrency":{"anyOf":[{"minimum":1,"type":"integer"},{"type":"null"}],"default":null,"title":"Max Concurrency"}},"required":["max_concurrency"],"title":"LLMConcurrencyOverrideSettings","type":"object"};

function validate60(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate60.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((data.max_concurrency === undefined) && (missing0 = "max_concurrency")){
validate60.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.max_concurrency !== undefined){
let data0 = data.max_concurrency;
const _errs2 = errors;
let valid1 = false;
const _errs3 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
const err0 = {instancePath:instancePath+"/max_concurrency",schemaPath:"#/properties/max_concurrency/anyOf/0/type",keyword:"type",params:{type: "integer"},message:"must be integer"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
if(errors === _errs3){
if(typeof data0 == "number"){
if(data0 < 1 || isNaN(data0)){
const err1 = {instancePath:instancePath+"/max_concurrency",schemaPath:"#/properties/max_concurrency/anyOf/0/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
}
}
var _valid0 = _errs3 === errors;
valid1 = valid1 || _valid0;
const _errs5 = errors;
if(data0 !== null){
const err2 = {instancePath:instancePath+"/max_concurrency",schemaPath:"#/properties/max_concurrency/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
}
var _valid0 = _errs5 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err3 = {instancePath:instancePath+"/max_concurrency",schemaPath:"#/properties/max_concurrency/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
validate60.errors = vErrors;
return false;
}
else {
errors = _errs2;
if(vErrors !== null){
if(_errs2){
vErrors.length = _errs2;
}
else {
vErrors = null;
}
}
}
}
}
}
else {
validate60.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate60.errors = vErrors;
return errors === 0;
}
validate60.evaluated = {"props":{"max_concurrency":true},"dynamicProps":false,"dynamicItems":false};

const schema26 = {"properties":{"api_format":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Api Format"},"api_key":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Api Key"},"base_url":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Base Url"},"custom_default_model":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Custom Default Model"},"custom_models":{"items":{"type":"string"},"title":"Custom Models","type":"array"},"display_name":{"default":"OpenAI","title":"Display Name","type":"string"},"enabled":{"default":true,"title":"Enabled","type":"boolean"},"model_metadata_overrides":{"additionalProperties":{"$ref":"#/components/schemas/LLMModelMetadataOverrideSettings"},"title":"Model Metadata Overrides","type":"object"},"provider_plan":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Provider Plan"},"provider_type":{"default":"openai","title":"Provider Type","type":"string"},"services":{"$ref":"#/components/schemas/LLMProviderServicesConfigModel"}},"required":["enabled","provider_type","display_name","provider_plan","api_key","base_url","services","api_format","custom_models","custom_default_model","model_metadata_overrides"],"title":"LLMProviderConfigModel","type":"object"};
const schema27 = {"description":"User-defined metadata override for any provider model.","properties":{"capabilities":{"$ref":"#/components/schemas/LLMCapabilityOverridesSettings"},"cost":{"anyOf":[{"$ref":"#/components/schemas/LLMModelCostModel"},{"type":"null"}],"default":null},"description":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Description"},"dimensions":{"anyOf":[{"items":{"type":"integer"},"type":"array"},{"type":"null"}],"default":null,"title":"Dimensions"},"hidden":{"anyOf":[{"type":"boolean"},{"type":"null"}],"default":null,"title":"Hidden"},"icon":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Icon"},"input_modalities":{"anyOf":[{"items":{"type":"string"},"type":"array"},{"type":"null"}],"default":null,"title":"Input Modalities"},"label":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Label"},"limits":{"$ref":"#/components/schemas/LLMLimitsOverrideSettings"},"output_modalities":{"anyOf":[{"items":{"type":"string"},"type":"array"},{"type":"null"}],"default":null,"title":"Output Modalities"},"preferred":{"anyOf":[{"type":"boolean"},{"type":"null"}],"default":null,"title":"Preferred"},"provider_options_example":{"anyOf":[{"additionalProperties":true,"type":"object"},{"type":"null"}],"default":null,"title":"Provider Options Example"},"source_note":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Source Note"},"vendor":{"anyOf":[{"$ref":"#/components/schemas/ModelVendor"},{"type":"null"}],"default":null,"description":"Behavioral vendor override. Set this on custom-gateway models (OneAPI etc.) so the runtime picks the correct reasoning / tool-calling payload shape rather than guessing from URL."}},"required":["label","description","icon","vendor","capabilities","limits","input_modalities","output_modalities","provider_options_example","cost","hidden","preferred","source_note","dimensions"],"title":"LLMModelMetadataOverrideSettings","type":"object"};
const schema28 = {"description":"Per-model capability overrides applied on top of registry metadata.","properties":{"embedding":{"anyOf":[{"type":"boolean"},{"type":"null"}],"default":null,"title":"Embedding"},"image_output":{"anyOf":[{"type":"boolean"},{"type":"null"}],"default":null,"title":"Image Output"},"reasoning":{"anyOf":[{"type":"boolean"},{"type":"null"}],"default":null,"title":"Reasoning"},"tool_calling":{"anyOf":[{"type":"boolean"},{"type":"null"}],"default":null,"title":"Tool Calling"},"vision":{"anyOf":[{"type":"boolean"},{"type":"null"}],"default":null,"title":"Vision"}},"required":["vision","image_output","tool_calling","reasoning","embedding"],"title":"LLMCapabilityOverridesSettings","type":"object"};

function validate64(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate64.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((data.vision === undefined) && (missing0 = "vision")) || ((data.image_output === undefined) && (missing0 = "image_output"))) || ((data.tool_calling === undefined) && (missing0 = "tool_calling"))) || ((data.reasoning === undefined) && (missing0 = "reasoning"))) || ((data.embedding === undefined) && (missing0 = "embedding"))){
validate64.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.embedding !== undefined){
let data0 = data.embedding;
const _errs1 = errors;
const _errs2 = errors;
let valid1 = false;
const _errs3 = errors;
if(typeof data0 !== "boolean"){
const err0 = {instancePath:instancePath+"/embedding",schemaPath:"#/properties/embedding/anyOf/0/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs3 === errors;
valid1 = valid1 || _valid0;
const _errs5 = errors;
if(data0 !== null){
const err1 = {instancePath:instancePath+"/embedding",schemaPath:"#/properties/embedding/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs5 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/embedding",schemaPath:"#/properties/embedding/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate64.errors = vErrors;
return false;
}
else {
errors = _errs2;
if(vErrors !== null){
if(_errs2){
vErrors.length = _errs2;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.image_output !== undefined){
let data1 = data.image_output;
const _errs7 = errors;
const _errs8 = errors;
let valid2 = false;
const _errs9 = errors;
if(typeof data1 !== "boolean"){
const err3 = {instancePath:instancePath+"/image_output",schemaPath:"#/properties/image_output/anyOf/0/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs9 === errors;
valid2 = valid2 || _valid1;
const _errs11 = errors;
if(data1 !== null){
const err4 = {instancePath:instancePath+"/image_output",schemaPath:"#/properties/image_output/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs11 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err5 = {instancePath:instancePath+"/image_output",schemaPath:"#/properties/image_output/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate64.errors = vErrors;
return false;
}
else {
errors = _errs8;
if(vErrors !== null){
if(_errs8){
vErrors.length = _errs8;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.reasoning !== undefined){
let data2 = data.reasoning;
const _errs13 = errors;
const _errs14 = errors;
let valid3 = false;
const _errs15 = errors;
if(typeof data2 !== "boolean"){
const err6 = {instancePath:instancePath+"/reasoning",schemaPath:"#/properties/reasoning/anyOf/0/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid2 = _errs15 === errors;
valid3 = valid3 || _valid2;
const _errs17 = errors;
if(data2 !== null){
const err7 = {instancePath:instancePath+"/reasoning",schemaPath:"#/properties/reasoning/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
}
var _valid2 = _errs17 === errors;
valid3 = valid3 || _valid2;
if(!valid3){
const err8 = {instancePath:instancePath+"/reasoning",schemaPath:"#/properties/reasoning/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
validate64.errors = vErrors;
return false;
}
else {
errors = _errs14;
if(vErrors !== null){
if(_errs14){
vErrors.length = _errs14;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.tool_calling !== undefined){
let data3 = data.tool_calling;
const _errs19 = errors;
const _errs20 = errors;
let valid4 = false;
const _errs21 = errors;
if(typeof data3 !== "boolean"){
const err9 = {instancePath:instancePath+"/tool_calling",schemaPath:"#/properties/tool_calling/anyOf/0/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"};
if(vErrors === null){
vErrors = [err9];
}
else {
vErrors.push(err9);
}
errors++;
}
var _valid3 = _errs21 === errors;
valid4 = valid4 || _valid3;
const _errs23 = errors;
if(data3 !== null){
const err10 = {instancePath:instancePath+"/tool_calling",schemaPath:"#/properties/tool_calling/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
}
var _valid3 = _errs23 === errors;
valid4 = valid4 || _valid3;
if(!valid4){
const err11 = {instancePath:instancePath+"/tool_calling",schemaPath:"#/properties/tool_calling/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err11];
}
else {
vErrors.push(err11);
}
errors++;
validate64.errors = vErrors;
return false;
}
else {
errors = _errs20;
if(vErrors !== null){
if(_errs20){
vErrors.length = _errs20;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs19 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.vision !== undefined){
let data4 = data.vision;
const _errs25 = errors;
const _errs26 = errors;
let valid5 = false;
const _errs27 = errors;
if(typeof data4 !== "boolean"){
const err12 = {instancePath:instancePath+"/vision",schemaPath:"#/properties/vision/anyOf/0/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"};
if(vErrors === null){
vErrors = [err12];
}
else {
vErrors.push(err12);
}
errors++;
}
var _valid4 = _errs27 === errors;
valid5 = valid5 || _valid4;
const _errs29 = errors;
if(data4 !== null){
const err13 = {instancePath:instancePath+"/vision",schemaPath:"#/properties/vision/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err13];
}
else {
vErrors.push(err13);
}
errors++;
}
var _valid4 = _errs29 === errors;
valid5 = valid5 || _valid4;
if(!valid5){
const err14 = {instancePath:instancePath+"/vision",schemaPath:"#/properties/vision/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err14];
}
else {
vErrors.push(err14);
}
errors++;
validate64.errors = vErrors;
return false;
}
else {
errors = _errs26;
if(vErrors !== null){
if(_errs26){
vErrors.length = _errs26;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs25 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
else {
validate64.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate64.errors = vErrors;
return errors === 0;
}
validate64.evaluated = {"props":{"embedding":true,"image_output":true,"reasoning":true,"tool_calling":true,"vision":true},"dynamicProps":false,"dynamicItems":false};

const schema29 = {"description":"Provider-published pricing metadata for a model.","properties":{"cache_write_per_million_tokens":{"anyOf":[{"minimum":0,"type":"number"},{"type":"null"}],"default":null,"title":"Cache Write Per Million Tokens"},"cached_input_per_million_tokens":{"anyOf":[{"minimum":0,"type":"number"},{"type":"null"}],"default":null,"title":"Cached Input Per Million Tokens"},"currency":{"default":"USD","title":"Currency","type":"string"},"input_per_million_tokens":{"anyOf":[{"minimum":0,"type":"number"},{"type":"null"}],"default":null,"title":"Input Per Million Tokens"},"output_per_million_tokens":{"anyOf":[{"minimum":0,"type":"number"},{"type":"null"}],"default":null,"title":"Output Per Million Tokens"},"per_image":{"anyOf":[{"minimum":0,"type":"number"},{"type":"null"}],"default":null,"title":"Per Image"},"source":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Source"},"source_note":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Source Note"}},"required":["currency","input_per_million_tokens","cached_input_per_million_tokens","cache_write_per_million_tokens","output_per_million_tokens","per_image","source","source_note"],"title":"LLMModelCostModel","type":"object"};

function validate66(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate66.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((((data.currency === undefined) && (missing0 = "currency")) || ((data.input_per_million_tokens === undefined) && (missing0 = "input_per_million_tokens"))) || ((data.cached_input_per_million_tokens === undefined) && (missing0 = "cached_input_per_million_tokens"))) || ((data.cache_write_per_million_tokens === undefined) && (missing0 = "cache_write_per_million_tokens"))) || ((data.output_per_million_tokens === undefined) && (missing0 = "output_per_million_tokens"))) || ((data.per_image === undefined) && (missing0 = "per_image"))) || ((data.source === undefined) && (missing0 = "source"))) || ((data.source_note === undefined) && (missing0 = "source_note"))){
validate66.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.cache_write_per_million_tokens !== undefined){
let data0 = data.cache_write_per_million_tokens;
const _errs1 = errors;
const _errs2 = errors;
let valid1 = false;
const _errs3 = errors;
if(errors === _errs3){
if(typeof data0 == "number"){
if(data0 < 0 || isNaN(data0)){
const err0 = {instancePath:instancePath+"/cache_write_per_million_tokens",schemaPath:"#/properties/cache_write_per_million_tokens/anyOf/0/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
}
else {
const err1 = {instancePath:instancePath+"/cache_write_per_million_tokens",schemaPath:"#/properties/cache_write_per_million_tokens/anyOf/0/type",keyword:"type",params:{type: "number"},message:"must be number"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
}
var _valid0 = _errs3 === errors;
valid1 = valid1 || _valid0;
const _errs5 = errors;
if(data0 !== null){
const err2 = {instancePath:instancePath+"/cache_write_per_million_tokens",schemaPath:"#/properties/cache_write_per_million_tokens/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
}
var _valid0 = _errs5 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err3 = {instancePath:instancePath+"/cache_write_per_million_tokens",schemaPath:"#/properties/cache_write_per_million_tokens/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
validate66.errors = vErrors;
return false;
}
else {
errors = _errs2;
if(vErrors !== null){
if(_errs2){
vErrors.length = _errs2;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.cached_input_per_million_tokens !== undefined){
let data1 = data.cached_input_per_million_tokens;
const _errs7 = errors;
const _errs8 = errors;
let valid2 = false;
const _errs9 = errors;
if(errors === _errs9){
if(typeof data1 == "number"){
if(data1 < 0 || isNaN(data1)){
const err4 = {instancePath:instancePath+"/cached_input_per_million_tokens",schemaPath:"#/properties/cached_input_per_million_tokens/anyOf/0/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
}
else {
const err5 = {instancePath:instancePath+"/cached_input_per_million_tokens",schemaPath:"#/properties/cached_input_per_million_tokens/anyOf/0/type",keyword:"type",params:{type: "number"},message:"must be number"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
}
}
var _valid1 = _errs9 === errors;
valid2 = valid2 || _valid1;
const _errs11 = errors;
if(data1 !== null){
const err6 = {instancePath:instancePath+"/cached_input_per_million_tokens",schemaPath:"#/properties/cached_input_per_million_tokens/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid1 = _errs11 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err7 = {instancePath:instancePath+"/cached_input_per_million_tokens",schemaPath:"#/properties/cached_input_per_million_tokens/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
validate66.errors = vErrors;
return false;
}
else {
errors = _errs8;
if(vErrors !== null){
if(_errs8){
vErrors.length = _errs8;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.currency !== undefined){
const _errs13 = errors;
if(typeof data.currency !== "string"){
validate66.errors = [{instancePath:instancePath+"/currency",schemaPath:"#/properties/currency/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.input_per_million_tokens !== undefined){
let data3 = data.input_per_million_tokens;
const _errs15 = errors;
const _errs16 = errors;
let valid3 = false;
const _errs17 = errors;
if(errors === _errs17){
if(typeof data3 == "number"){
if(data3 < 0 || isNaN(data3)){
const err8 = {instancePath:instancePath+"/input_per_million_tokens",schemaPath:"#/properties/input_per_million_tokens/anyOf/0/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
}
}
else {
const err9 = {instancePath:instancePath+"/input_per_million_tokens",schemaPath:"#/properties/input_per_million_tokens/anyOf/0/type",keyword:"type",params:{type: "number"},message:"must be number"};
if(vErrors === null){
vErrors = [err9];
}
else {
vErrors.push(err9);
}
errors++;
}
}
var _valid2 = _errs17 === errors;
valid3 = valid3 || _valid2;
const _errs19 = errors;
if(data3 !== null){
const err10 = {instancePath:instancePath+"/input_per_million_tokens",schemaPath:"#/properties/input_per_million_tokens/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
}
var _valid2 = _errs19 === errors;
valid3 = valid3 || _valid2;
if(!valid3){
const err11 = {instancePath:instancePath+"/input_per_million_tokens",schemaPath:"#/properties/input_per_million_tokens/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err11];
}
else {
vErrors.push(err11);
}
errors++;
validate66.errors = vErrors;
return false;
}
else {
errors = _errs16;
if(vErrors !== null){
if(_errs16){
vErrors.length = _errs16;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs15 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.output_per_million_tokens !== undefined){
let data4 = data.output_per_million_tokens;
const _errs21 = errors;
const _errs22 = errors;
let valid4 = false;
const _errs23 = errors;
if(errors === _errs23){
if(typeof data4 == "number"){
if(data4 < 0 || isNaN(data4)){
const err12 = {instancePath:instancePath+"/output_per_million_tokens",schemaPath:"#/properties/output_per_million_tokens/anyOf/0/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"};
if(vErrors === null){
vErrors = [err12];
}
else {
vErrors.push(err12);
}
errors++;
}
}
else {
const err13 = {instancePath:instancePath+"/output_per_million_tokens",schemaPath:"#/properties/output_per_million_tokens/anyOf/0/type",keyword:"type",params:{type: "number"},message:"must be number"};
if(vErrors === null){
vErrors = [err13];
}
else {
vErrors.push(err13);
}
errors++;
}
}
var _valid3 = _errs23 === errors;
valid4 = valid4 || _valid3;
const _errs25 = errors;
if(data4 !== null){
const err14 = {instancePath:instancePath+"/output_per_million_tokens",schemaPath:"#/properties/output_per_million_tokens/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err14];
}
else {
vErrors.push(err14);
}
errors++;
}
var _valid3 = _errs25 === errors;
valid4 = valid4 || _valid3;
if(!valid4){
const err15 = {instancePath:instancePath+"/output_per_million_tokens",schemaPath:"#/properties/output_per_million_tokens/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err15];
}
else {
vErrors.push(err15);
}
errors++;
validate66.errors = vErrors;
return false;
}
else {
errors = _errs22;
if(vErrors !== null){
if(_errs22){
vErrors.length = _errs22;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs21 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.per_image !== undefined){
let data5 = data.per_image;
const _errs27 = errors;
const _errs28 = errors;
let valid5 = false;
const _errs29 = errors;
if(errors === _errs29){
if(typeof data5 == "number"){
if(data5 < 0 || isNaN(data5)){
const err16 = {instancePath:instancePath+"/per_image",schemaPath:"#/properties/per_image/anyOf/0/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"};
if(vErrors === null){
vErrors = [err16];
}
else {
vErrors.push(err16);
}
errors++;
}
}
else {
const err17 = {instancePath:instancePath+"/per_image",schemaPath:"#/properties/per_image/anyOf/0/type",keyword:"type",params:{type: "number"},message:"must be number"};
if(vErrors === null){
vErrors = [err17];
}
else {
vErrors.push(err17);
}
errors++;
}
}
var _valid4 = _errs29 === errors;
valid5 = valid5 || _valid4;
const _errs31 = errors;
if(data5 !== null){
const err18 = {instancePath:instancePath+"/per_image",schemaPath:"#/properties/per_image/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err18];
}
else {
vErrors.push(err18);
}
errors++;
}
var _valid4 = _errs31 === errors;
valid5 = valid5 || _valid4;
if(!valid5){
const err19 = {instancePath:instancePath+"/per_image",schemaPath:"#/properties/per_image/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err19];
}
else {
vErrors.push(err19);
}
errors++;
validate66.errors = vErrors;
return false;
}
else {
errors = _errs28;
if(vErrors !== null){
if(_errs28){
vErrors.length = _errs28;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs27 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.source !== undefined){
let data6 = data.source;
const _errs33 = errors;
const _errs34 = errors;
let valid6 = false;
const _errs35 = errors;
if(typeof data6 !== "string"){
const err20 = {instancePath:instancePath+"/source",schemaPath:"#/properties/source/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err20];
}
else {
vErrors.push(err20);
}
errors++;
}
var _valid5 = _errs35 === errors;
valid6 = valid6 || _valid5;
const _errs37 = errors;
if(data6 !== null){
const err21 = {instancePath:instancePath+"/source",schemaPath:"#/properties/source/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err21];
}
else {
vErrors.push(err21);
}
errors++;
}
var _valid5 = _errs37 === errors;
valid6 = valid6 || _valid5;
if(!valid6){
const err22 = {instancePath:instancePath+"/source",schemaPath:"#/properties/source/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err22];
}
else {
vErrors.push(err22);
}
errors++;
validate66.errors = vErrors;
return false;
}
else {
errors = _errs34;
if(vErrors !== null){
if(_errs34){
vErrors.length = _errs34;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs33 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.source_note !== undefined){
let data7 = data.source_note;
const _errs39 = errors;
const _errs40 = errors;
let valid7 = false;
const _errs41 = errors;
if(typeof data7 !== "string"){
const err23 = {instancePath:instancePath+"/source_note",schemaPath:"#/properties/source_note/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err23];
}
else {
vErrors.push(err23);
}
errors++;
}
var _valid6 = _errs41 === errors;
valid7 = valid7 || _valid6;
const _errs43 = errors;
if(data7 !== null){
const err24 = {instancePath:instancePath+"/source_note",schemaPath:"#/properties/source_note/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err24];
}
else {
vErrors.push(err24);
}
errors++;
}
var _valid6 = _errs43 === errors;
valid7 = valid7 || _valid6;
if(!valid7){
const err25 = {instancePath:instancePath+"/source_note",schemaPath:"#/properties/source_note/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err25];
}
else {
vErrors.push(err25);
}
errors++;
validate66.errors = vErrors;
return false;
}
else {
errors = _errs40;
if(vErrors !== null){
if(_errs40){
vErrors.length = _errs40;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs39 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
}
else {
validate66.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate66.errors = vErrors;
return errors === 0;
}
validate66.evaluated = {"props":{"cache_write_per_million_tokens":true,"cached_input_per_million_tokens":true,"currency":true,"input_per_million_tokens":true,"output_per_million_tokens":true,"per_image":true,"source":true,"source_note":true},"dynamicProps":false,"dynamicItems":false};

const schema30 = {"description":"Per-model numeric limit overrides applied on top of registry metadata.","properties":{"context_window":{"anyOf":[{"minimum":1,"type":"integer"},{"type":"null"}],"default":null,"title":"Context Window"},"max_output_tokens":{"anyOf":[{"minimum":1,"type":"integer"},{"type":"null"}],"default":null,"title":"Max Output Tokens"},"max_schema_tokens":{"anyOf":[{"minimum":1,"type":"integer"},{"type":"null"}],"default":null,"title":"Max Schema Tokens"},"max_tool_schemas":{"anyOf":[{"minimum":1,"type":"integer"},{"type":"null"}],"default":null,"title":"Max Tool Schemas"}},"required":["context_window","max_output_tokens","max_tool_schemas","max_schema_tokens"],"title":"LLMLimitsOverrideSettings","type":"object"};

function validate68(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate68.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((data.context_window === undefined) && (missing0 = "context_window")) || ((data.max_output_tokens === undefined) && (missing0 = "max_output_tokens"))) || ((data.max_tool_schemas === undefined) && (missing0 = "max_tool_schemas"))) || ((data.max_schema_tokens === undefined) && (missing0 = "max_schema_tokens"))){
validate68.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.context_window !== undefined){
let data0 = data.context_window;
const _errs1 = errors;
const _errs2 = errors;
let valid1 = false;
const _errs3 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
const err0 = {instancePath:instancePath+"/context_window",schemaPath:"#/properties/context_window/anyOf/0/type",keyword:"type",params:{type: "integer"},message:"must be integer"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
if(errors === _errs3){
if(typeof data0 == "number"){
if(data0 < 1 || isNaN(data0)){
const err1 = {instancePath:instancePath+"/context_window",schemaPath:"#/properties/context_window/anyOf/0/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
}
}
var _valid0 = _errs3 === errors;
valid1 = valid1 || _valid0;
const _errs5 = errors;
if(data0 !== null){
const err2 = {instancePath:instancePath+"/context_window",schemaPath:"#/properties/context_window/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
}
var _valid0 = _errs5 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err3 = {instancePath:instancePath+"/context_window",schemaPath:"#/properties/context_window/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
validate68.errors = vErrors;
return false;
}
else {
errors = _errs2;
if(vErrors !== null){
if(_errs2){
vErrors.length = _errs2;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.max_output_tokens !== undefined){
let data1 = data.max_output_tokens;
const _errs7 = errors;
const _errs8 = errors;
let valid2 = false;
const _errs9 = errors;
if(!((typeof data1 == "number") && (!(data1 % 1) && !isNaN(data1)))){
const err4 = {instancePath:instancePath+"/max_output_tokens",schemaPath:"#/properties/max_output_tokens/anyOf/0/type",keyword:"type",params:{type: "integer"},message:"must be integer"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
if(errors === _errs9){
if(typeof data1 == "number"){
if(data1 < 1 || isNaN(data1)){
const err5 = {instancePath:instancePath+"/max_output_tokens",schemaPath:"#/properties/max_output_tokens/anyOf/0/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
}
}
}
var _valid1 = _errs9 === errors;
valid2 = valid2 || _valid1;
const _errs11 = errors;
if(data1 !== null){
const err6 = {instancePath:instancePath+"/max_output_tokens",schemaPath:"#/properties/max_output_tokens/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid1 = _errs11 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err7 = {instancePath:instancePath+"/max_output_tokens",schemaPath:"#/properties/max_output_tokens/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
validate68.errors = vErrors;
return false;
}
else {
errors = _errs8;
if(vErrors !== null){
if(_errs8){
vErrors.length = _errs8;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.max_schema_tokens !== undefined){
let data2 = data.max_schema_tokens;
const _errs13 = errors;
const _errs14 = errors;
let valid3 = false;
const _errs15 = errors;
if(!((typeof data2 == "number") && (!(data2 % 1) && !isNaN(data2)))){
const err8 = {instancePath:instancePath+"/max_schema_tokens",schemaPath:"#/properties/max_schema_tokens/anyOf/0/type",keyword:"type",params:{type: "integer"},message:"must be integer"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
}
if(errors === _errs15){
if(typeof data2 == "number"){
if(data2 < 1 || isNaN(data2)){
const err9 = {instancePath:instancePath+"/max_schema_tokens",schemaPath:"#/properties/max_schema_tokens/anyOf/0/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"};
if(vErrors === null){
vErrors = [err9];
}
else {
vErrors.push(err9);
}
errors++;
}
}
}
var _valid2 = _errs15 === errors;
valid3 = valid3 || _valid2;
const _errs17 = errors;
if(data2 !== null){
const err10 = {instancePath:instancePath+"/max_schema_tokens",schemaPath:"#/properties/max_schema_tokens/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
}
var _valid2 = _errs17 === errors;
valid3 = valid3 || _valid2;
if(!valid3){
const err11 = {instancePath:instancePath+"/max_schema_tokens",schemaPath:"#/properties/max_schema_tokens/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err11];
}
else {
vErrors.push(err11);
}
errors++;
validate68.errors = vErrors;
return false;
}
else {
errors = _errs14;
if(vErrors !== null){
if(_errs14){
vErrors.length = _errs14;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.max_tool_schemas !== undefined){
let data3 = data.max_tool_schemas;
const _errs19 = errors;
const _errs20 = errors;
let valid4 = false;
const _errs21 = errors;
if(!((typeof data3 == "number") && (!(data3 % 1) && !isNaN(data3)))){
const err12 = {instancePath:instancePath+"/max_tool_schemas",schemaPath:"#/properties/max_tool_schemas/anyOf/0/type",keyword:"type",params:{type: "integer"},message:"must be integer"};
if(vErrors === null){
vErrors = [err12];
}
else {
vErrors.push(err12);
}
errors++;
}
if(errors === _errs21){
if(typeof data3 == "number"){
if(data3 < 1 || isNaN(data3)){
const err13 = {instancePath:instancePath+"/max_tool_schemas",schemaPath:"#/properties/max_tool_schemas/anyOf/0/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"};
if(vErrors === null){
vErrors = [err13];
}
else {
vErrors.push(err13);
}
errors++;
}
}
}
var _valid3 = _errs21 === errors;
valid4 = valid4 || _valid3;
const _errs23 = errors;
if(data3 !== null){
const err14 = {instancePath:instancePath+"/max_tool_schemas",schemaPath:"#/properties/max_tool_schemas/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err14];
}
else {
vErrors.push(err14);
}
errors++;
}
var _valid3 = _errs23 === errors;
valid4 = valid4 || _valid3;
if(!valid4){
const err15 = {instancePath:instancePath+"/max_tool_schemas",schemaPath:"#/properties/max_tool_schemas/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err15];
}
else {
vErrors.push(err15);
}
errors++;
validate68.errors = vErrors;
return false;
}
else {
errors = _errs20;
if(vErrors !== null){
if(_errs20){
vErrors.length = _errs20;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs19 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
else {
validate68.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate68.errors = vErrors;
return errors === 0;
}
validate68.evaluated = {"props":{"context_window":true,"max_output_tokens":true,"max_schema_tokens":true,"max_tool_schemas":true},"dynamicProps":false,"dynamicItems":false};

const schema31 = {"description":"The behavioral vendor a model belongs to.\n\n``provider`` is *who hosts the endpoint* (which can be an OneAPI-style\ngateway). ``vendor`` is *who built the model* and therefore decides\npayload shape: how reasoning is expressed, how tool-calling is\nserialized, where system prompts live, etc.\n\nA single OneAPI gateway may proxy ``glm-4-plus`` (vendor=GLM),\n``qwen-max`` (vendor=DASHSCOPE), and ``claude-sonnet-4-6``\n(vendor=ANTHROPIC) under the same ``provider``. Routing dialects off\nprovider name would misroute each of these; routing off vendor is\ncorrect.\n\n``GENERIC`` means \"OpenAI-compatible transport, no vendor-specific\nextensions\"; reasoning / thinking knobs are not injected.","enum":["openai","deepseek","anthropic","glm","dashscope","grok","gemini","kimi","minimax","generic"],"title":"ModelVendor","type":"string"};

function validate70(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate70.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(typeof data !== "string"){
validate70.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((((((((((data === "openai") || (data === "deepseek")) || (data === "anthropic")) || (data === "glm")) || (data === "dashscope")) || (data === "grok")) || (data === "gemini")) || (data === "kimi")) || (data === "minimax")) || (data === "generic"))){
validate70.errors = [{instancePath,schemaPath:"#/enum",keyword:"enum",params:{allowedValues: schema31.enum},message:"must be equal to one of the allowed values"}];
return false;
}
validate70.errors = vErrors;
return errors === 0;
}
validate70.evaluated = {"dynamicProps":false,"dynamicItems":false};


function validate63(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate63.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((((((((((data.label === undefined) && (missing0 = "label")) || ((data.description === undefined) && (missing0 = "description"))) || ((data.icon === undefined) && (missing0 = "icon"))) || ((data.vendor === undefined) && (missing0 = "vendor"))) || ((data.capabilities === undefined) && (missing0 = "capabilities"))) || ((data.limits === undefined) && (missing0 = "limits"))) || ((data.input_modalities === undefined) && (missing0 = "input_modalities"))) || ((data.output_modalities === undefined) && (missing0 = "output_modalities"))) || ((data.provider_options_example === undefined) && (missing0 = "provider_options_example"))) || ((data.cost === undefined) && (missing0 = "cost"))) || ((data.hidden === undefined) && (missing0 = "hidden"))) || ((data.preferred === undefined) && (missing0 = "preferred"))) || ((data.source_note === undefined) && (missing0 = "source_note"))) || ((data.dimensions === undefined) && (missing0 = "dimensions"))){
validate63.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.capabilities !== undefined){
const _errs1 = errors;
if(!(validate64(data.capabilities, {instancePath:instancePath+"/capabilities",parentData:data,parentDataProperty:"capabilities",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate64.errors : vErrors.concat(validate64.errors);
errors = vErrors.length;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.cost !== undefined){
let data1 = data.cost;
const _errs2 = errors;
const _errs3 = errors;
let valid1 = false;
const _errs4 = errors;
if(!(validate66(data1, {instancePath:instancePath+"/cost",parentData:data,parentDataProperty:"cost",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate66.errors : vErrors.concat(validate66.errors);
errors = vErrors.length;
}
var _valid0 = _errs4 === errors;
valid1 = valid1 || _valid0;
if(_valid0){
var props0 = {};
props0.cache_write_per_million_tokens = true;
props0.cached_input_per_million_tokens = true;
props0.currency = true;
props0.input_per_million_tokens = true;
props0.output_per_million_tokens = true;
props0.per_image = true;
props0.source = true;
props0.source_note = true;
}
const _errs5 = errors;
if(data1 !== null){
const err0 = {instancePath:instancePath+"/cost",schemaPath:"#/properties/cost/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs5 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err1 = {instancePath:instancePath+"/cost",schemaPath:"#/properties/cost/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
validate63.errors = vErrors;
return false;
}
else {
errors = _errs3;
if(vErrors !== null){
if(_errs3){
vErrors.length = _errs3;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description !== undefined){
let data2 = data.description;
const _errs7 = errors;
const _errs8 = errors;
let valid2 = false;
const _errs9 = errors;
if(typeof data2 !== "string"){
const err2 = {instancePath:instancePath+"/description",schemaPath:"#/properties/description/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
}
var _valid1 = _errs9 === errors;
valid2 = valid2 || _valid1;
const _errs11 = errors;
if(data2 !== null){
const err3 = {instancePath:instancePath+"/description",schemaPath:"#/properties/description/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs11 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err4 = {instancePath:instancePath+"/description",schemaPath:"#/properties/description/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
validate63.errors = vErrors;
return false;
}
else {
errors = _errs8;
if(vErrors !== null){
if(_errs8){
vErrors.length = _errs8;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.dimensions !== undefined){
let data3 = data.dimensions;
const _errs13 = errors;
const _errs14 = errors;
let valid3 = false;
const _errs15 = errors;
if(errors === _errs15){
if(Array.isArray(data3)){
var valid4 = true;
const len0 = data3.length;
for(let i0=0; i0<len0; i0++){
let data4 = data3[i0];
const _errs17 = errors;
if(!((typeof data4 == "number") && (!(data4 % 1) && !isNaN(data4)))){
const err5 = {instancePath:instancePath+"/dimensions/" + i0,schemaPath:"#/properties/dimensions/anyOf/0/items/type",keyword:"type",params:{type: "integer"},message:"must be integer"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
}
var valid4 = _errs17 === errors;
if(!valid4){
break;
}
}
}
else {
const err6 = {instancePath:instancePath+"/dimensions",schemaPath:"#/properties/dimensions/anyOf/0/type",keyword:"type",params:{type: "array"},message:"must be array"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
}
var _valid2 = _errs15 === errors;
valid3 = valid3 || _valid2;
const _errs19 = errors;
if(data3 !== null){
const err7 = {instancePath:instancePath+"/dimensions",schemaPath:"#/properties/dimensions/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
}
var _valid2 = _errs19 === errors;
valid3 = valid3 || _valid2;
if(!valid3){
const err8 = {instancePath:instancePath+"/dimensions",schemaPath:"#/properties/dimensions/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
validate63.errors = vErrors;
return false;
}
else {
errors = _errs14;
if(vErrors !== null){
if(_errs14){
vErrors.length = _errs14;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.hidden !== undefined){
let data5 = data.hidden;
const _errs21 = errors;
const _errs22 = errors;
let valid5 = false;
const _errs23 = errors;
if(typeof data5 !== "boolean"){
const err9 = {instancePath:instancePath+"/hidden",schemaPath:"#/properties/hidden/anyOf/0/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"};
if(vErrors === null){
vErrors = [err9];
}
else {
vErrors.push(err9);
}
errors++;
}
var _valid3 = _errs23 === errors;
valid5 = valid5 || _valid3;
const _errs25 = errors;
if(data5 !== null){
const err10 = {instancePath:instancePath+"/hidden",schemaPath:"#/properties/hidden/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
}
var _valid3 = _errs25 === errors;
valid5 = valid5 || _valid3;
if(!valid5){
const err11 = {instancePath:instancePath+"/hidden",schemaPath:"#/properties/hidden/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err11];
}
else {
vErrors.push(err11);
}
errors++;
validate63.errors = vErrors;
return false;
}
else {
errors = _errs22;
if(vErrors !== null){
if(_errs22){
vErrors.length = _errs22;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs21 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.icon !== undefined){
let data6 = data.icon;
const _errs27 = errors;
const _errs28 = errors;
let valid6 = false;
const _errs29 = errors;
if(typeof data6 !== "string"){
const err12 = {instancePath:instancePath+"/icon",schemaPath:"#/properties/icon/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err12];
}
else {
vErrors.push(err12);
}
errors++;
}
var _valid4 = _errs29 === errors;
valid6 = valid6 || _valid4;
const _errs31 = errors;
if(data6 !== null){
const err13 = {instancePath:instancePath+"/icon",schemaPath:"#/properties/icon/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err13];
}
else {
vErrors.push(err13);
}
errors++;
}
var _valid4 = _errs31 === errors;
valid6 = valid6 || _valid4;
if(!valid6){
const err14 = {instancePath:instancePath+"/icon",schemaPath:"#/properties/icon/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err14];
}
else {
vErrors.push(err14);
}
errors++;
validate63.errors = vErrors;
return false;
}
else {
errors = _errs28;
if(vErrors !== null){
if(_errs28){
vErrors.length = _errs28;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs27 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.input_modalities !== undefined){
let data7 = data.input_modalities;
const _errs33 = errors;
const _errs34 = errors;
let valid7 = false;
const _errs35 = errors;
if(errors === _errs35){
if(Array.isArray(data7)){
var valid8 = true;
const len1 = data7.length;
for(let i1=0; i1<len1; i1++){
const _errs37 = errors;
if(typeof data7[i1] !== "string"){
const err15 = {instancePath:instancePath+"/input_modalities/" + i1,schemaPath:"#/properties/input_modalities/anyOf/0/items/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err15];
}
else {
vErrors.push(err15);
}
errors++;
}
var valid8 = _errs37 === errors;
if(!valid8){
break;
}
}
}
else {
const err16 = {instancePath:instancePath+"/input_modalities",schemaPath:"#/properties/input_modalities/anyOf/0/type",keyword:"type",params:{type: "array"},message:"must be array"};
if(vErrors === null){
vErrors = [err16];
}
else {
vErrors.push(err16);
}
errors++;
}
}
var _valid5 = _errs35 === errors;
valid7 = valid7 || _valid5;
const _errs39 = errors;
if(data7 !== null){
const err17 = {instancePath:instancePath+"/input_modalities",schemaPath:"#/properties/input_modalities/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err17];
}
else {
vErrors.push(err17);
}
errors++;
}
var _valid5 = _errs39 === errors;
valid7 = valid7 || _valid5;
if(!valid7){
const err18 = {instancePath:instancePath+"/input_modalities",schemaPath:"#/properties/input_modalities/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err18];
}
else {
vErrors.push(err18);
}
errors++;
validate63.errors = vErrors;
return false;
}
else {
errors = _errs34;
if(vErrors !== null){
if(_errs34){
vErrors.length = _errs34;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs33 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.label !== undefined){
let data9 = data.label;
const _errs41 = errors;
const _errs42 = errors;
let valid9 = false;
const _errs43 = errors;
if(typeof data9 !== "string"){
const err19 = {instancePath:instancePath+"/label",schemaPath:"#/properties/label/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err19];
}
else {
vErrors.push(err19);
}
errors++;
}
var _valid6 = _errs43 === errors;
valid9 = valid9 || _valid6;
const _errs45 = errors;
if(data9 !== null){
const err20 = {instancePath:instancePath+"/label",schemaPath:"#/properties/label/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err20];
}
else {
vErrors.push(err20);
}
errors++;
}
var _valid6 = _errs45 === errors;
valid9 = valid9 || _valid6;
if(!valid9){
const err21 = {instancePath:instancePath+"/label",schemaPath:"#/properties/label/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err21];
}
else {
vErrors.push(err21);
}
errors++;
validate63.errors = vErrors;
return false;
}
else {
errors = _errs42;
if(vErrors !== null){
if(_errs42){
vErrors.length = _errs42;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs41 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.limits !== undefined){
const _errs47 = errors;
if(!(validate68(data.limits, {instancePath:instancePath+"/limits",parentData:data,parentDataProperty:"limits",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate68.errors : vErrors.concat(validate68.errors);
errors = vErrors.length;
}
var valid0 = _errs47 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.output_modalities !== undefined){
let data11 = data.output_modalities;
const _errs48 = errors;
const _errs49 = errors;
let valid10 = false;
const _errs50 = errors;
if(errors === _errs50){
if(Array.isArray(data11)){
var valid11 = true;
const len2 = data11.length;
for(let i2=0; i2<len2; i2++){
const _errs52 = errors;
if(typeof data11[i2] !== "string"){
const err22 = {instancePath:instancePath+"/output_modalities/" + i2,schemaPath:"#/properties/output_modalities/anyOf/0/items/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err22];
}
else {
vErrors.push(err22);
}
errors++;
}
var valid11 = _errs52 === errors;
if(!valid11){
break;
}
}
}
else {
const err23 = {instancePath:instancePath+"/output_modalities",schemaPath:"#/properties/output_modalities/anyOf/0/type",keyword:"type",params:{type: "array"},message:"must be array"};
if(vErrors === null){
vErrors = [err23];
}
else {
vErrors.push(err23);
}
errors++;
}
}
var _valid7 = _errs50 === errors;
valid10 = valid10 || _valid7;
const _errs54 = errors;
if(data11 !== null){
const err24 = {instancePath:instancePath+"/output_modalities",schemaPath:"#/properties/output_modalities/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err24];
}
else {
vErrors.push(err24);
}
errors++;
}
var _valid7 = _errs54 === errors;
valid10 = valid10 || _valid7;
if(!valid10){
const err25 = {instancePath:instancePath+"/output_modalities",schemaPath:"#/properties/output_modalities/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err25];
}
else {
vErrors.push(err25);
}
errors++;
validate63.errors = vErrors;
return false;
}
else {
errors = _errs49;
if(vErrors !== null){
if(_errs49){
vErrors.length = _errs49;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs48 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.preferred !== undefined){
let data13 = data.preferred;
const _errs56 = errors;
const _errs57 = errors;
let valid12 = false;
const _errs58 = errors;
if(typeof data13 !== "boolean"){
const err26 = {instancePath:instancePath+"/preferred",schemaPath:"#/properties/preferred/anyOf/0/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"};
if(vErrors === null){
vErrors = [err26];
}
else {
vErrors.push(err26);
}
errors++;
}
var _valid8 = _errs58 === errors;
valid12 = valid12 || _valid8;
const _errs60 = errors;
if(data13 !== null){
const err27 = {instancePath:instancePath+"/preferred",schemaPath:"#/properties/preferred/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err27];
}
else {
vErrors.push(err27);
}
errors++;
}
var _valid8 = _errs60 === errors;
valid12 = valid12 || _valid8;
if(!valid12){
const err28 = {instancePath:instancePath+"/preferred",schemaPath:"#/properties/preferred/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err28];
}
else {
vErrors.push(err28);
}
errors++;
validate63.errors = vErrors;
return false;
}
else {
errors = _errs57;
if(vErrors !== null){
if(_errs57){
vErrors.length = _errs57;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs56 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.provider_options_example !== undefined){
let data14 = data.provider_options_example;
const _errs62 = errors;
const _errs63 = errors;
let valid13 = false;
const _errs64 = errors;
if(errors === _errs64){
if(data14 && typeof data14 == "object" && !Array.isArray(data14)){
}
else {
const err29 = {instancePath:instancePath+"/provider_options_example",schemaPath:"#/properties/provider_options_example/anyOf/0/type",keyword:"type",params:{type: "object"},message:"must be object"};
if(vErrors === null){
vErrors = [err29];
}
else {
vErrors.push(err29);
}
errors++;
}
}
var _valid9 = _errs64 === errors;
valid13 = valid13 || _valid9;
const _errs67 = errors;
if(data14 !== null){
const err30 = {instancePath:instancePath+"/provider_options_example",schemaPath:"#/properties/provider_options_example/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err30];
}
else {
vErrors.push(err30);
}
errors++;
}
var _valid9 = _errs67 === errors;
valid13 = valid13 || _valid9;
if(!valid13){
const err31 = {instancePath:instancePath+"/provider_options_example",schemaPath:"#/properties/provider_options_example/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err31];
}
else {
vErrors.push(err31);
}
errors++;
validate63.errors = vErrors;
return false;
}
else {
errors = _errs63;
if(vErrors !== null){
if(_errs63){
vErrors.length = _errs63;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs62 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.source_note !== undefined){
let data15 = data.source_note;
const _errs69 = errors;
const _errs70 = errors;
let valid14 = false;
const _errs71 = errors;
if(typeof data15 !== "string"){
const err32 = {instancePath:instancePath+"/source_note",schemaPath:"#/properties/source_note/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err32];
}
else {
vErrors.push(err32);
}
errors++;
}
var _valid10 = _errs71 === errors;
valid14 = valid14 || _valid10;
const _errs73 = errors;
if(data15 !== null){
const err33 = {instancePath:instancePath+"/source_note",schemaPath:"#/properties/source_note/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err33];
}
else {
vErrors.push(err33);
}
errors++;
}
var _valid10 = _errs73 === errors;
valid14 = valid14 || _valid10;
if(!valid14){
const err34 = {instancePath:instancePath+"/source_note",schemaPath:"#/properties/source_note/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err34];
}
else {
vErrors.push(err34);
}
errors++;
validate63.errors = vErrors;
return false;
}
else {
errors = _errs70;
if(vErrors !== null){
if(_errs70){
vErrors.length = _errs70;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs69 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.vendor !== undefined){
let data16 = data.vendor;
const _errs75 = errors;
const _errs76 = errors;
let valid15 = false;
const _errs77 = errors;
if(!(validate70(data16, {instancePath:instancePath+"/vendor",parentData:data,parentDataProperty:"vendor",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate70.errors : vErrors.concat(validate70.errors);
errors = vErrors.length;
}
var _valid11 = _errs77 === errors;
valid15 = valid15 || _valid11;
const _errs78 = errors;
if(data16 !== null){
const err35 = {instancePath:instancePath+"/vendor",schemaPath:"#/properties/vendor/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err35];
}
else {
vErrors.push(err35);
}
errors++;
}
var _valid11 = _errs78 === errors;
valid15 = valid15 || _valid11;
if(!valid15){
const err36 = {instancePath:instancePath+"/vendor",schemaPath:"#/properties/vendor/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err36];
}
else {
vErrors.push(err36);
}
errors++;
validate63.errors = vErrors;
return false;
}
else {
errors = _errs76;
if(vErrors !== null){
if(_errs76){
vErrors.length = _errs76;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs75 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
else {
validate63.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate63.errors = vErrors;
return errors === 0;
}
validate63.evaluated = {"props":{"capabilities":true,"cost":true,"description":true,"dimensions":true,"hidden":true,"icon":true,"input_modalities":true,"label":true,"limits":true,"output_modalities":true,"preferred":true,"provider_options_example":true,"source_note":true,"vendor":true},"dynamicProps":false,"dynamicItems":false};

const schema32 = {"properties":{"chat":{"$ref":"#/components/schemas/LLMProviderConnectionConfigModel"},"embedding":{"$ref":"#/components/schemas/LLMProviderConnectionConfigModel"},"image_generation":{"$ref":"#/components/schemas/LLMProviderImageGenerationConfigModel"},"tts":{"$ref":"#/components/schemas/LLMProviderTTSConfigModel"}},"required":["chat","embedding","image_generation","tts"],"title":"LLMProviderServicesConfigModel","type":"object"};
const schema33 = {"properties":{"api_key":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Api Key"},"base_url":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Base Url"},"enabled":{"default":true,"title":"Enabled","type":"boolean"}},"required":["enabled","api_key","base_url"],"title":"LLMProviderConnectionConfigModel","type":"object"};

function validate74(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate74.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((data.enabled === undefined) && (missing0 = "enabled")) || ((data.api_key === undefined) && (missing0 = "api_key"))) || ((data.base_url === undefined) && (missing0 = "base_url"))){
validate74.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.api_key !== undefined){
let data0 = data.api_key;
const _errs1 = errors;
const _errs2 = errors;
let valid1 = false;
const _errs3 = errors;
if(typeof data0 !== "string"){
const err0 = {instancePath:instancePath+"/api_key",schemaPath:"#/properties/api_key/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs3 === errors;
valid1 = valid1 || _valid0;
const _errs5 = errors;
if(data0 !== null){
const err1 = {instancePath:instancePath+"/api_key",schemaPath:"#/properties/api_key/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs5 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/api_key",schemaPath:"#/properties/api_key/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate74.errors = vErrors;
return false;
}
else {
errors = _errs2;
if(vErrors !== null){
if(_errs2){
vErrors.length = _errs2;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.base_url !== undefined){
let data1 = data.base_url;
const _errs7 = errors;
const _errs8 = errors;
let valid2 = false;
const _errs9 = errors;
if(typeof data1 !== "string"){
const err3 = {instancePath:instancePath+"/base_url",schemaPath:"#/properties/base_url/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs9 === errors;
valid2 = valid2 || _valid1;
const _errs11 = errors;
if(data1 !== null){
const err4 = {instancePath:instancePath+"/base_url",schemaPath:"#/properties/base_url/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs11 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err5 = {instancePath:instancePath+"/base_url",schemaPath:"#/properties/base_url/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate74.errors = vErrors;
return false;
}
else {
errors = _errs8;
if(vErrors !== null){
if(_errs8){
vErrors.length = _errs8;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.enabled !== undefined){
const _errs13 = errors;
if(typeof data.enabled !== "boolean"){
validate74.errors = [{instancePath:instancePath+"/enabled",schemaPath:"#/properties/enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
else {
validate74.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate74.errors = vErrors;
return errors === 0;
}
validate74.evaluated = {"props":{"api_key":true,"base_url":true,"enabled":true},"dynamicProps":false,"dynamicItems":false};

const schema34 = {"properties":{"api_key":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Api Key"},"base_url":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Base Url"},"enabled":{"default":false,"title":"Enabled","type":"boolean"},"native_protocol":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Native Protocol"},"timeout":{"default":180,"minimum":1,"title":"Timeout","type":"integer"}},"required":["enabled","api_key","base_url","timeout","native_protocol"],"title":"LLMProviderImageGenerationConfigModel","type":"object"};

function validate77(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate77.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((data.enabled === undefined) && (missing0 = "enabled")) || ((data.api_key === undefined) && (missing0 = "api_key"))) || ((data.base_url === undefined) && (missing0 = "base_url"))) || ((data.timeout === undefined) && (missing0 = "timeout"))) || ((data.native_protocol === undefined) && (missing0 = "native_protocol"))){
validate77.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.api_key !== undefined){
let data0 = data.api_key;
const _errs1 = errors;
const _errs2 = errors;
let valid1 = false;
const _errs3 = errors;
if(typeof data0 !== "string"){
const err0 = {instancePath:instancePath+"/api_key",schemaPath:"#/properties/api_key/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs3 === errors;
valid1 = valid1 || _valid0;
const _errs5 = errors;
if(data0 !== null){
const err1 = {instancePath:instancePath+"/api_key",schemaPath:"#/properties/api_key/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs5 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/api_key",schemaPath:"#/properties/api_key/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate77.errors = vErrors;
return false;
}
else {
errors = _errs2;
if(vErrors !== null){
if(_errs2){
vErrors.length = _errs2;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.base_url !== undefined){
let data1 = data.base_url;
const _errs7 = errors;
const _errs8 = errors;
let valid2 = false;
const _errs9 = errors;
if(typeof data1 !== "string"){
const err3 = {instancePath:instancePath+"/base_url",schemaPath:"#/properties/base_url/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs9 === errors;
valid2 = valid2 || _valid1;
const _errs11 = errors;
if(data1 !== null){
const err4 = {instancePath:instancePath+"/base_url",schemaPath:"#/properties/base_url/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs11 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err5 = {instancePath:instancePath+"/base_url",schemaPath:"#/properties/base_url/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate77.errors = vErrors;
return false;
}
else {
errors = _errs8;
if(vErrors !== null){
if(_errs8){
vErrors.length = _errs8;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.enabled !== undefined){
const _errs13 = errors;
if(typeof data.enabled !== "boolean"){
validate77.errors = [{instancePath:instancePath+"/enabled",schemaPath:"#/properties/enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.native_protocol !== undefined){
let data3 = data.native_protocol;
const _errs15 = errors;
const _errs16 = errors;
let valid3 = false;
const _errs17 = errors;
if(typeof data3 !== "string"){
const err6 = {instancePath:instancePath+"/native_protocol",schemaPath:"#/properties/native_protocol/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid2 = _errs17 === errors;
valid3 = valid3 || _valid2;
const _errs19 = errors;
if(data3 !== null){
const err7 = {instancePath:instancePath+"/native_protocol",schemaPath:"#/properties/native_protocol/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
}
var _valid2 = _errs19 === errors;
valid3 = valid3 || _valid2;
if(!valid3){
const err8 = {instancePath:instancePath+"/native_protocol",schemaPath:"#/properties/native_protocol/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
validate77.errors = vErrors;
return false;
}
else {
errors = _errs16;
if(vErrors !== null){
if(_errs16){
vErrors.length = _errs16;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs15 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.timeout !== undefined){
let data4 = data.timeout;
const _errs21 = errors;
if(!((typeof data4 == "number") && (!(data4 % 1) && !isNaN(data4)))){
validate77.errors = [{instancePath:instancePath+"/timeout",schemaPath:"#/properties/timeout/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs21){
if(typeof data4 == "number"){
if(data4 < 1 || isNaN(data4)){
validate77.errors = [{instancePath:instancePath+"/timeout",schemaPath:"#/properties/timeout/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"}];
return false;
}
}
}
var valid0 = _errs21 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
else {
validate77.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate77.errors = vErrors;
return errors === 0;
}
validate77.evaluated = {"props":{"api_key":true,"base_url":true,"enabled":true,"native_protocol":true,"timeout":true},"dynamicProps":false,"dynamicItems":false};

const schema35 = {"properties":{"api_key":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Api Key"},"base_url":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Base Url"},"enabled":{"default":false,"title":"Enabled","type":"boolean"},"model":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Model"},"response_format":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Response Format"},"voice":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Voice"}},"required":["enabled","api_key","base_url","model","voice","response_format"],"title":"LLMProviderTTSConfigModel","type":"object"};

function validate79(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate79.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((data.enabled === undefined) && (missing0 = "enabled")) || ((data.api_key === undefined) && (missing0 = "api_key"))) || ((data.base_url === undefined) && (missing0 = "base_url"))) || ((data.model === undefined) && (missing0 = "model"))) || ((data.voice === undefined) && (missing0 = "voice"))) || ((data.response_format === undefined) && (missing0 = "response_format"))){
validate79.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.api_key !== undefined){
let data0 = data.api_key;
const _errs1 = errors;
const _errs2 = errors;
let valid1 = false;
const _errs3 = errors;
if(typeof data0 !== "string"){
const err0 = {instancePath:instancePath+"/api_key",schemaPath:"#/properties/api_key/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs3 === errors;
valid1 = valid1 || _valid0;
const _errs5 = errors;
if(data0 !== null){
const err1 = {instancePath:instancePath+"/api_key",schemaPath:"#/properties/api_key/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs5 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/api_key",schemaPath:"#/properties/api_key/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate79.errors = vErrors;
return false;
}
else {
errors = _errs2;
if(vErrors !== null){
if(_errs2){
vErrors.length = _errs2;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.base_url !== undefined){
let data1 = data.base_url;
const _errs7 = errors;
const _errs8 = errors;
let valid2 = false;
const _errs9 = errors;
if(typeof data1 !== "string"){
const err3 = {instancePath:instancePath+"/base_url",schemaPath:"#/properties/base_url/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs9 === errors;
valid2 = valid2 || _valid1;
const _errs11 = errors;
if(data1 !== null){
const err4 = {instancePath:instancePath+"/base_url",schemaPath:"#/properties/base_url/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs11 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err5 = {instancePath:instancePath+"/base_url",schemaPath:"#/properties/base_url/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate79.errors = vErrors;
return false;
}
else {
errors = _errs8;
if(vErrors !== null){
if(_errs8){
vErrors.length = _errs8;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.enabled !== undefined){
const _errs13 = errors;
if(typeof data.enabled !== "boolean"){
validate79.errors = [{instancePath:instancePath+"/enabled",schemaPath:"#/properties/enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.model !== undefined){
let data3 = data.model;
const _errs15 = errors;
const _errs16 = errors;
let valid3 = false;
const _errs17 = errors;
if(typeof data3 !== "string"){
const err6 = {instancePath:instancePath+"/model",schemaPath:"#/properties/model/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid2 = _errs17 === errors;
valid3 = valid3 || _valid2;
const _errs19 = errors;
if(data3 !== null){
const err7 = {instancePath:instancePath+"/model",schemaPath:"#/properties/model/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
}
var _valid2 = _errs19 === errors;
valid3 = valid3 || _valid2;
if(!valid3){
const err8 = {instancePath:instancePath+"/model",schemaPath:"#/properties/model/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
validate79.errors = vErrors;
return false;
}
else {
errors = _errs16;
if(vErrors !== null){
if(_errs16){
vErrors.length = _errs16;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs15 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.response_format !== undefined){
let data4 = data.response_format;
const _errs21 = errors;
const _errs22 = errors;
let valid4 = false;
const _errs23 = errors;
if(typeof data4 !== "string"){
const err9 = {instancePath:instancePath+"/response_format",schemaPath:"#/properties/response_format/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err9];
}
else {
vErrors.push(err9);
}
errors++;
}
var _valid3 = _errs23 === errors;
valid4 = valid4 || _valid3;
const _errs25 = errors;
if(data4 !== null){
const err10 = {instancePath:instancePath+"/response_format",schemaPath:"#/properties/response_format/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
}
var _valid3 = _errs25 === errors;
valid4 = valid4 || _valid3;
if(!valid4){
const err11 = {instancePath:instancePath+"/response_format",schemaPath:"#/properties/response_format/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err11];
}
else {
vErrors.push(err11);
}
errors++;
validate79.errors = vErrors;
return false;
}
else {
errors = _errs22;
if(vErrors !== null){
if(_errs22){
vErrors.length = _errs22;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs21 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.voice !== undefined){
let data5 = data.voice;
const _errs27 = errors;
const _errs28 = errors;
let valid5 = false;
const _errs29 = errors;
if(typeof data5 !== "string"){
const err12 = {instancePath:instancePath+"/voice",schemaPath:"#/properties/voice/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err12];
}
else {
vErrors.push(err12);
}
errors++;
}
var _valid4 = _errs29 === errors;
valid5 = valid5 || _valid4;
const _errs31 = errors;
if(data5 !== null){
const err13 = {instancePath:instancePath+"/voice",schemaPath:"#/properties/voice/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err13];
}
else {
vErrors.push(err13);
}
errors++;
}
var _valid4 = _errs31 === errors;
valid5 = valid5 || _valid4;
if(!valid5){
const err14 = {instancePath:instancePath+"/voice",schemaPath:"#/properties/voice/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err14];
}
else {
vErrors.push(err14);
}
errors++;
validate79.errors = vErrors;
return false;
}
else {
errors = _errs28;
if(vErrors !== null){
if(_errs28){
vErrors.length = _errs28;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs27 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
else {
validate79.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate79.errors = vErrors;
return errors === 0;
}
validate79.evaluated = {"props":{"api_key":true,"base_url":true,"enabled":true,"model":true,"response_format":true,"voice":true},"dynamicProps":false,"dynamicItems":false};


function validate73(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate73.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((data.chat === undefined) && (missing0 = "chat")) || ((data.embedding === undefined) && (missing0 = "embedding"))) || ((data.image_generation === undefined) && (missing0 = "image_generation"))) || ((data.tts === undefined) && (missing0 = "tts"))){
validate73.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.chat !== undefined){
const _errs1 = errors;
if(!(validate74(data.chat, {instancePath:instancePath+"/chat",parentData:data,parentDataProperty:"chat",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate74.errors : vErrors.concat(validate74.errors);
errors = vErrors.length;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.embedding !== undefined){
const _errs2 = errors;
if(!(validate74(data.embedding, {instancePath:instancePath+"/embedding",parentData:data,parentDataProperty:"embedding",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate74.errors : vErrors.concat(validate74.errors);
errors = vErrors.length;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.image_generation !== undefined){
const _errs3 = errors;
if(!(validate77(data.image_generation, {instancePath:instancePath+"/image_generation",parentData:data,parentDataProperty:"image_generation",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate77.errors : vErrors.concat(validate77.errors);
errors = vErrors.length;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.tts !== undefined){
const _errs4 = errors;
if(!(validate79(data.tts, {instancePath:instancePath+"/tts",parentData:data,parentDataProperty:"tts",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate79.errors : vErrors.concat(validate79.errors);
errors = vErrors.length;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
else {
validate73.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate73.errors = vErrors;
return errors === 0;
}
validate73.evaluated = {"props":{"chat":true,"embedding":true,"image_generation":true,"tts":true},"dynamicProps":false,"dynamicItems":false};


function validate62(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate62.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((((((((data.enabled === undefined) && (missing0 = "enabled")) || ((data.provider_type === undefined) && (missing0 = "provider_type"))) || ((data.display_name === undefined) && (missing0 = "display_name"))) || ((data.provider_plan === undefined) && (missing0 = "provider_plan"))) || ((data.api_key === undefined) && (missing0 = "api_key"))) || ((data.base_url === undefined) && (missing0 = "base_url"))) || ((data.services === undefined) && (missing0 = "services"))) || ((data.api_format === undefined) && (missing0 = "api_format"))) || ((data.custom_models === undefined) && (missing0 = "custom_models"))) || ((data.custom_default_model === undefined) && (missing0 = "custom_default_model"))) || ((data.model_metadata_overrides === undefined) && (missing0 = "model_metadata_overrides"))){
validate62.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.api_format !== undefined){
let data0 = data.api_format;
const _errs1 = errors;
const _errs2 = errors;
let valid1 = false;
const _errs3 = errors;
if(typeof data0 !== "string"){
const err0 = {instancePath:instancePath+"/api_format",schemaPath:"#/properties/api_format/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs3 === errors;
valid1 = valid1 || _valid0;
const _errs5 = errors;
if(data0 !== null){
const err1 = {instancePath:instancePath+"/api_format",schemaPath:"#/properties/api_format/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs5 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/api_format",schemaPath:"#/properties/api_format/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate62.errors = vErrors;
return false;
}
else {
errors = _errs2;
if(vErrors !== null){
if(_errs2){
vErrors.length = _errs2;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.api_key !== undefined){
let data1 = data.api_key;
const _errs7 = errors;
const _errs8 = errors;
let valid2 = false;
const _errs9 = errors;
if(typeof data1 !== "string"){
const err3 = {instancePath:instancePath+"/api_key",schemaPath:"#/properties/api_key/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs9 === errors;
valid2 = valid2 || _valid1;
const _errs11 = errors;
if(data1 !== null){
const err4 = {instancePath:instancePath+"/api_key",schemaPath:"#/properties/api_key/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs11 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err5 = {instancePath:instancePath+"/api_key",schemaPath:"#/properties/api_key/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate62.errors = vErrors;
return false;
}
else {
errors = _errs8;
if(vErrors !== null){
if(_errs8){
vErrors.length = _errs8;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.base_url !== undefined){
let data2 = data.base_url;
const _errs13 = errors;
const _errs14 = errors;
let valid3 = false;
const _errs15 = errors;
if(typeof data2 !== "string"){
const err6 = {instancePath:instancePath+"/base_url",schemaPath:"#/properties/base_url/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid2 = _errs15 === errors;
valid3 = valid3 || _valid2;
const _errs17 = errors;
if(data2 !== null){
const err7 = {instancePath:instancePath+"/base_url",schemaPath:"#/properties/base_url/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
}
var _valid2 = _errs17 === errors;
valid3 = valid3 || _valid2;
if(!valid3){
const err8 = {instancePath:instancePath+"/base_url",schemaPath:"#/properties/base_url/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
validate62.errors = vErrors;
return false;
}
else {
errors = _errs14;
if(vErrors !== null){
if(_errs14){
vErrors.length = _errs14;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.custom_default_model !== undefined){
let data3 = data.custom_default_model;
const _errs19 = errors;
const _errs20 = errors;
let valid4 = false;
const _errs21 = errors;
if(typeof data3 !== "string"){
const err9 = {instancePath:instancePath+"/custom_default_model",schemaPath:"#/properties/custom_default_model/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err9];
}
else {
vErrors.push(err9);
}
errors++;
}
var _valid3 = _errs21 === errors;
valid4 = valid4 || _valid3;
const _errs23 = errors;
if(data3 !== null){
const err10 = {instancePath:instancePath+"/custom_default_model",schemaPath:"#/properties/custom_default_model/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
}
var _valid3 = _errs23 === errors;
valid4 = valid4 || _valid3;
if(!valid4){
const err11 = {instancePath:instancePath+"/custom_default_model",schemaPath:"#/properties/custom_default_model/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err11];
}
else {
vErrors.push(err11);
}
errors++;
validate62.errors = vErrors;
return false;
}
else {
errors = _errs20;
if(vErrors !== null){
if(_errs20){
vErrors.length = _errs20;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs19 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.custom_models !== undefined){
let data4 = data.custom_models;
const _errs25 = errors;
if(errors === _errs25){
if(Array.isArray(data4)){
var valid5 = true;
const len0 = data4.length;
for(let i0=0; i0<len0; i0++){
const _errs27 = errors;
if(typeof data4[i0] !== "string"){
validate62.errors = [{instancePath:instancePath+"/custom_models/" + i0,schemaPath:"#/properties/custom_models/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid5 = _errs27 === errors;
if(!valid5){
break;
}
}
}
else {
validate62.errors = [{instancePath:instancePath+"/custom_models",schemaPath:"#/properties/custom_models/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs25 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.display_name !== undefined){
const _errs29 = errors;
if(typeof data.display_name !== "string"){
validate62.errors = [{instancePath:instancePath+"/display_name",schemaPath:"#/properties/display_name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs29 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.enabled !== undefined){
const _errs31 = errors;
if(typeof data.enabled !== "boolean"){
validate62.errors = [{instancePath:instancePath+"/enabled",schemaPath:"#/properties/enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs31 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.model_metadata_overrides !== undefined){
let data8 = data.model_metadata_overrides;
const _errs33 = errors;
if(errors === _errs33){
if(data8 && typeof data8 == "object" && !Array.isArray(data8)){
for(const key0 in data8){
const _errs36 = errors;
if(!(validate63(data8[key0], {instancePath:instancePath+"/model_metadata_overrides/" + key0.replace(/~/g, "~0").replace(/\//g, "~1"),parentData:data8,parentDataProperty:key0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate63.errors : vErrors.concat(validate63.errors);
errors = vErrors.length;
}
var valid6 = _errs36 === errors;
if(!valid6){
break;
}
}
}
else {
validate62.errors = [{instancePath:instancePath+"/model_metadata_overrides",schemaPath:"#/properties/model_metadata_overrides/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs33 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.provider_plan !== undefined){
let data10 = data.provider_plan;
const _errs37 = errors;
const _errs38 = errors;
let valid7 = false;
const _errs39 = errors;
if(typeof data10 !== "string"){
const err12 = {instancePath:instancePath+"/provider_plan",schemaPath:"#/properties/provider_plan/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err12];
}
else {
vErrors.push(err12);
}
errors++;
}
var _valid4 = _errs39 === errors;
valid7 = valid7 || _valid4;
const _errs41 = errors;
if(data10 !== null){
const err13 = {instancePath:instancePath+"/provider_plan",schemaPath:"#/properties/provider_plan/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err13];
}
else {
vErrors.push(err13);
}
errors++;
}
var _valid4 = _errs41 === errors;
valid7 = valid7 || _valid4;
if(!valid7){
const err14 = {instancePath:instancePath+"/provider_plan",schemaPath:"#/properties/provider_plan/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err14];
}
else {
vErrors.push(err14);
}
errors++;
validate62.errors = vErrors;
return false;
}
else {
errors = _errs38;
if(vErrors !== null){
if(_errs38){
vErrors.length = _errs38;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs37 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.provider_type !== undefined){
const _errs43 = errors;
if(typeof data.provider_type !== "string"){
validate62.errors = [{instancePath:instancePath+"/provider_type",schemaPath:"#/properties/provider_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs43 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.services !== undefined){
const _errs45 = errors;
if(!(validate73(data.services, {instancePath:instancePath+"/services",parentData:data,parentDataProperty:"services",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate73.errors : vErrors.concat(validate73.errors);
errors = vErrors.length;
}
var valid0 = _errs45 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
}
}
}
}
else {
validate62.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate62.errors = vErrors;
return errors === 0;
}
validate62.evaluated = {"props":{"api_format":true,"api_key":true,"base_url":true,"custom_default_model":true,"custom_models":true,"display_name":true,"enabled":true,"model_metadata_overrides":true,"provider_plan":true,"provider_type":true,"services":true},"dynamicProps":false,"dynamicItems":false};

const schema36 = {"properties":{"capabilities":{"$ref":"#/components/schemas/LLMCapabilitiesSettings"},"capability_override_enabled":{"default":false,"title":"Capability Override Enabled","type":"boolean"},"embedding_dimension":{"anyOf":[{"minimum":1,"type":"integer"},{"type":"null"}],"default":null,"title":"Embedding Dimension"},"limits":{"$ref":"#/components/schemas/LLMSelectionLimitsSettings"},"model":{"default":"","title":"Model","type":"string"},"provider_id":{"default":"","title":"Provider Id","type":"string"},"provider_options":{"additionalProperties":true,"title":"Provider Options","type":"object"}},"required":["provider_id","model","embedding_dimension","capability_override_enabled","capabilities","limits","provider_options"],"title":"LLMSelectionConfigModel","type":"object"};
const schema37 = {"description":"Declared capability flags for the active LLM.","properties":{"embedding":{"default":false,"title":"Embedding","type":"boolean"},"image_output":{"default":false,"title":"Image Output","type":"boolean"},"reasoning":{"default":true,"title":"Reasoning","type":"boolean"},"tool_calling":{"default":true,"title":"Tool Calling","type":"boolean"},"vision":{"default":false,"title":"Vision","type":"boolean"}},"required":["vision","image_output","tool_calling","reasoning","embedding"],"title":"LLMCapabilitiesSettings","type":"object"};

function validate84(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate84.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((data.vision === undefined) && (missing0 = "vision")) || ((data.image_output === undefined) && (missing0 = "image_output"))) || ((data.tool_calling === undefined) && (missing0 = "tool_calling"))) || ((data.reasoning === undefined) && (missing0 = "reasoning"))) || ((data.embedding === undefined) && (missing0 = "embedding"))){
validate84.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.embedding !== undefined){
const _errs1 = errors;
if(typeof data.embedding !== "boolean"){
validate84.errors = [{instancePath:instancePath+"/embedding",schemaPath:"#/properties/embedding/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.image_output !== undefined){
const _errs3 = errors;
if(typeof data.image_output !== "boolean"){
validate84.errors = [{instancePath:instancePath+"/image_output",schemaPath:"#/properties/image_output/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.reasoning !== undefined){
const _errs5 = errors;
if(typeof data.reasoning !== "boolean"){
validate84.errors = [{instancePath:instancePath+"/reasoning",schemaPath:"#/properties/reasoning/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.tool_calling !== undefined){
const _errs7 = errors;
if(typeof data.tool_calling !== "boolean"){
validate84.errors = [{instancePath:instancePath+"/tool_calling",schemaPath:"#/properties/tool_calling/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.vision !== undefined){
const _errs9 = errors;
if(typeof data.vision !== "boolean"){
validate84.errors = [{instancePath:instancePath+"/vision",schemaPath:"#/properties/vision/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
else {
validate84.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate84.errors = vErrors;
return errors === 0;
}
validate84.evaluated = {"props":{"embedding":true,"image_output":true,"reasoning":true,"tool_calling":true,"vision":true},"dynamicProps":false,"dynamicItems":false};

const schema38 = {"description":"Per-scenario numeric limits that remain local to scenario selection.","properties":{"context_window":{"anyOf":[{"minimum":1,"type":"integer"},{"type":"null"}],"default":null,"title":"Context Window"},"max_output_tokens":{"anyOf":[{"minimum":1,"type":"integer"},{"type":"null"}],"default":null,"title":"Max Output Tokens"},"max_schema_tokens":{"anyOf":[{"minimum":1,"type":"integer"},{"type":"null"}],"default":null,"title":"Max Schema Tokens"},"max_tool_schemas":{"anyOf":[{"minimum":1,"type":"integer"},{"type":"null"}],"default":null,"title":"Max Tool Schemas"}},"required":["context_window","max_output_tokens","max_tool_schemas","max_schema_tokens"],"title":"LLMSelectionLimitsSettings","type":"object"};

function validate86(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate86.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((data.context_window === undefined) && (missing0 = "context_window")) || ((data.max_output_tokens === undefined) && (missing0 = "max_output_tokens"))) || ((data.max_tool_schemas === undefined) && (missing0 = "max_tool_schemas"))) || ((data.max_schema_tokens === undefined) && (missing0 = "max_schema_tokens"))){
validate86.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.context_window !== undefined){
let data0 = data.context_window;
const _errs1 = errors;
const _errs2 = errors;
let valid1 = false;
const _errs3 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
const err0 = {instancePath:instancePath+"/context_window",schemaPath:"#/properties/context_window/anyOf/0/type",keyword:"type",params:{type: "integer"},message:"must be integer"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
if(errors === _errs3){
if(typeof data0 == "number"){
if(data0 < 1 || isNaN(data0)){
const err1 = {instancePath:instancePath+"/context_window",schemaPath:"#/properties/context_window/anyOf/0/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
}
}
var _valid0 = _errs3 === errors;
valid1 = valid1 || _valid0;
const _errs5 = errors;
if(data0 !== null){
const err2 = {instancePath:instancePath+"/context_window",schemaPath:"#/properties/context_window/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
}
var _valid0 = _errs5 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err3 = {instancePath:instancePath+"/context_window",schemaPath:"#/properties/context_window/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
validate86.errors = vErrors;
return false;
}
else {
errors = _errs2;
if(vErrors !== null){
if(_errs2){
vErrors.length = _errs2;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.max_output_tokens !== undefined){
let data1 = data.max_output_tokens;
const _errs7 = errors;
const _errs8 = errors;
let valid2 = false;
const _errs9 = errors;
if(!((typeof data1 == "number") && (!(data1 % 1) && !isNaN(data1)))){
const err4 = {instancePath:instancePath+"/max_output_tokens",schemaPath:"#/properties/max_output_tokens/anyOf/0/type",keyword:"type",params:{type: "integer"},message:"must be integer"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
if(errors === _errs9){
if(typeof data1 == "number"){
if(data1 < 1 || isNaN(data1)){
const err5 = {instancePath:instancePath+"/max_output_tokens",schemaPath:"#/properties/max_output_tokens/anyOf/0/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
}
}
}
var _valid1 = _errs9 === errors;
valid2 = valid2 || _valid1;
const _errs11 = errors;
if(data1 !== null){
const err6 = {instancePath:instancePath+"/max_output_tokens",schemaPath:"#/properties/max_output_tokens/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid1 = _errs11 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err7 = {instancePath:instancePath+"/max_output_tokens",schemaPath:"#/properties/max_output_tokens/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
validate86.errors = vErrors;
return false;
}
else {
errors = _errs8;
if(vErrors !== null){
if(_errs8){
vErrors.length = _errs8;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.max_schema_tokens !== undefined){
let data2 = data.max_schema_tokens;
const _errs13 = errors;
const _errs14 = errors;
let valid3 = false;
const _errs15 = errors;
if(!((typeof data2 == "number") && (!(data2 % 1) && !isNaN(data2)))){
const err8 = {instancePath:instancePath+"/max_schema_tokens",schemaPath:"#/properties/max_schema_tokens/anyOf/0/type",keyword:"type",params:{type: "integer"},message:"must be integer"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
}
if(errors === _errs15){
if(typeof data2 == "number"){
if(data2 < 1 || isNaN(data2)){
const err9 = {instancePath:instancePath+"/max_schema_tokens",schemaPath:"#/properties/max_schema_tokens/anyOf/0/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"};
if(vErrors === null){
vErrors = [err9];
}
else {
vErrors.push(err9);
}
errors++;
}
}
}
var _valid2 = _errs15 === errors;
valid3 = valid3 || _valid2;
const _errs17 = errors;
if(data2 !== null){
const err10 = {instancePath:instancePath+"/max_schema_tokens",schemaPath:"#/properties/max_schema_tokens/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
}
var _valid2 = _errs17 === errors;
valid3 = valid3 || _valid2;
if(!valid3){
const err11 = {instancePath:instancePath+"/max_schema_tokens",schemaPath:"#/properties/max_schema_tokens/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err11];
}
else {
vErrors.push(err11);
}
errors++;
validate86.errors = vErrors;
return false;
}
else {
errors = _errs14;
if(vErrors !== null){
if(_errs14){
vErrors.length = _errs14;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.max_tool_schemas !== undefined){
let data3 = data.max_tool_schemas;
const _errs19 = errors;
const _errs20 = errors;
let valid4 = false;
const _errs21 = errors;
if(!((typeof data3 == "number") && (!(data3 % 1) && !isNaN(data3)))){
const err12 = {instancePath:instancePath+"/max_tool_schemas",schemaPath:"#/properties/max_tool_schemas/anyOf/0/type",keyword:"type",params:{type: "integer"},message:"must be integer"};
if(vErrors === null){
vErrors = [err12];
}
else {
vErrors.push(err12);
}
errors++;
}
if(errors === _errs21){
if(typeof data3 == "number"){
if(data3 < 1 || isNaN(data3)){
const err13 = {instancePath:instancePath+"/max_tool_schemas",schemaPath:"#/properties/max_tool_schemas/anyOf/0/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"};
if(vErrors === null){
vErrors = [err13];
}
else {
vErrors.push(err13);
}
errors++;
}
}
}
var _valid3 = _errs21 === errors;
valid4 = valid4 || _valid3;
const _errs23 = errors;
if(data3 !== null){
const err14 = {instancePath:instancePath+"/max_tool_schemas",schemaPath:"#/properties/max_tool_schemas/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err14];
}
else {
vErrors.push(err14);
}
errors++;
}
var _valid3 = _errs23 === errors;
valid4 = valid4 || _valid3;
if(!valid4){
const err15 = {instancePath:instancePath+"/max_tool_schemas",schemaPath:"#/properties/max_tool_schemas/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err15];
}
else {
vErrors.push(err15);
}
errors++;
validate86.errors = vErrors;
return false;
}
else {
errors = _errs20;
if(vErrors !== null){
if(_errs20){
vErrors.length = _errs20;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs19 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
else {
validate86.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate86.errors = vErrors;
return errors === 0;
}
validate86.evaluated = {"props":{"context_window":true,"max_output_tokens":true,"max_schema_tokens":true,"max_tool_schemas":true},"dynamicProps":false,"dynamicItems":false};


function validate83(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate83.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((((data.provider_id === undefined) && (missing0 = "provider_id")) || ((data.model === undefined) && (missing0 = "model"))) || ((data.embedding_dimension === undefined) && (missing0 = "embedding_dimension"))) || ((data.capability_override_enabled === undefined) && (missing0 = "capability_override_enabled"))) || ((data.capabilities === undefined) && (missing0 = "capabilities"))) || ((data.limits === undefined) && (missing0 = "limits"))) || ((data.provider_options === undefined) && (missing0 = "provider_options"))){
validate83.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.capabilities !== undefined){
const _errs1 = errors;
if(!(validate84(data.capabilities, {instancePath:instancePath+"/capabilities",parentData:data,parentDataProperty:"capabilities",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate84.errors : vErrors.concat(validate84.errors);
errors = vErrors.length;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.capability_override_enabled !== undefined){
const _errs2 = errors;
if(typeof data.capability_override_enabled !== "boolean"){
validate83.errors = [{instancePath:instancePath+"/capability_override_enabled",schemaPath:"#/properties/capability_override_enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.embedding_dimension !== undefined){
let data2 = data.embedding_dimension;
const _errs4 = errors;
const _errs5 = errors;
let valid1 = false;
const _errs6 = errors;
if(!((typeof data2 == "number") && (!(data2 % 1) && !isNaN(data2)))){
const err0 = {instancePath:instancePath+"/embedding_dimension",schemaPath:"#/properties/embedding_dimension/anyOf/0/type",keyword:"type",params:{type: "integer"},message:"must be integer"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
if(errors === _errs6){
if(typeof data2 == "number"){
if(data2 < 1 || isNaN(data2)){
const err1 = {instancePath:instancePath+"/embedding_dimension",schemaPath:"#/properties/embedding_dimension/anyOf/0/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
}
}
var _valid0 = _errs6 === errors;
valid1 = valid1 || _valid0;
const _errs8 = errors;
if(data2 !== null){
const err2 = {instancePath:instancePath+"/embedding_dimension",schemaPath:"#/properties/embedding_dimension/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
}
var _valid0 = _errs8 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err3 = {instancePath:instancePath+"/embedding_dimension",schemaPath:"#/properties/embedding_dimension/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
validate83.errors = vErrors;
return false;
}
else {
errors = _errs5;
if(vErrors !== null){
if(_errs5){
vErrors.length = _errs5;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.limits !== undefined){
const _errs10 = errors;
if(!(validate86(data.limits, {instancePath:instancePath+"/limits",parentData:data,parentDataProperty:"limits",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate86.errors : vErrors.concat(validate86.errors);
errors = vErrors.length;
}
var valid0 = _errs10 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.model !== undefined){
const _errs11 = errors;
if(typeof data.model !== "string"){
validate83.errors = [{instancePath:instancePath+"/model",schemaPath:"#/properties/model/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.provider_id !== undefined){
const _errs13 = errors;
if(typeof data.provider_id !== "string"){
validate83.errors = [{instancePath:instancePath+"/provider_id",schemaPath:"#/properties/provider_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.provider_options !== undefined){
let data6 = data.provider_options;
const _errs15 = errors;
if(errors === _errs15){
if(data6 && typeof data6 == "object" && !Array.isArray(data6)){
}
else {
validate83.errors = [{instancePath:instancePath+"/provider_options",schemaPath:"#/properties/provider_options/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs15 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
else {
validate83.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate83.errors = vErrors;
return errors === 0;
}
validate83.evaluated = {"props":{"capabilities":true,"capability_override_enabled":true,"embedding_dimension":true,"limits":true,"model":true,"provider_id":true,"provider_options":true},"dynamicProps":false,"dynamicItems":false};


function validate59(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate59.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((data.providers === undefined) && (missing0 = "providers")) || ((data.selections === undefined) && (missing0 = "selections"))) || ((data.model_runtime_overrides === undefined) && (missing0 = "model_runtime_overrides"))){
validate59.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.model_runtime_overrides !== undefined){
let data0 = data.model_runtime_overrides;
const _errs1 = errors;
if(errors === _errs1){
if(data0 && typeof data0 == "object" && !Array.isArray(data0)){
for(const key0 in data0){
const _errs4 = errors;
if(!(validate60(data0[key0], {instancePath:instancePath+"/model_runtime_overrides/" + key0.replace(/~/g, "~0").replace(/\//g, "~1"),parentData:data0,parentDataProperty:key0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate60.errors : vErrors.concat(validate60.errors);
errors = vErrors.length;
}
var valid1 = _errs4 === errors;
if(!valid1){
break;
}
}
}
else {
validate59.errors = [{instancePath:instancePath+"/model_runtime_overrides",schemaPath:"#/properties/model_runtime_overrides/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.providers !== undefined){
let data2 = data.providers;
const _errs5 = errors;
if(errors === _errs5){
if(data2 && typeof data2 == "object" && !Array.isArray(data2)){
for(const key1 in data2){
const _errs8 = errors;
if(!(validate62(data2[key1], {instancePath:instancePath+"/providers/" + key1.replace(/~/g, "~0").replace(/\//g, "~1"),parentData:data2,parentDataProperty:key1,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate62.errors : vErrors.concat(validate62.errors);
errors = vErrors.length;
}
var valid2 = _errs8 === errors;
if(!valid2){
break;
}
}
}
else {
validate59.errors = [{instancePath:instancePath+"/providers",schemaPath:"#/properties/providers/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.selections !== undefined){
let data4 = data.selections;
const _errs9 = errors;
if(errors === _errs9){
if(data4 && typeof data4 == "object" && !Array.isArray(data4)){
for(const key2 in data4){
const _errs12 = errors;
if(!(validate83(data4[key2], {instancePath:instancePath+"/selections/" + key2.replace(/~/g, "~0").replace(/\//g, "~1"),parentData:data4,parentDataProperty:key2,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate83.errors : vErrors.concat(validate83.errors);
errors = vErrors.length;
}
var valid3 = _errs12 === errors;
if(!valid3){
break;
}
}
}
else {
validate59.errors = [{instancePath:instancePath+"/selections",schemaPath:"#/properties/selections/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
else {
validate59.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate59.errors = vErrors;
return errors === 0;
}
validate59.evaluated = {"props":{"model_runtime_overrides":true,"providers":true,"selections":true},"dynamicProps":false,"dynamicItems":false};

const schema39 = {"properties":{"archive_path":{"anyOf":[{"type":"string"},{"type":"null"}],"title":"Archive Path"},"db_path":{"anyOf":[{"type":"string"},{"type":"null"}],"title":"Db Path"},"embedding":{"$ref":"#/components/schemas/EmbeddingConfigModel"},"entity_semantic_edges":{"$ref":"#/components/schemas/EntitySemanticEdgeConfigModel"},"graph_spreading":{"$ref":"#/components/schemas/GraphSpreadingConfigModel"},"history_behavior":{"default":"delete","title":"History Behavior","type":"string"},"l0":{"$ref":"#/components/schemas/MemoryL0ConfigModel"},"l1":{"$ref":"#/components/schemas/MemoryL1ConfigModel"},"l2":{"$ref":"#/components/schemas/MemoryL2ConfigModel"},"l3":{"$ref":"#/components/schemas/MemoryL3ConfigModel"},"l4":{"$ref":"#/components/schemas/MemoryL4ConfigModel"},"query_expansion":{"$ref":"#/components/schemas/QueryExpansionConfigModel"},"reranker":{"$ref":"#/components/schemas/MemoryRerankerConfigModel"},"retention_days":{"default":90,"minimum":1,"title":"Retention Days","type":"integer"}},"required":["db_path","retention_days","history_behavior","archive_path","embedding","reranker","query_expansion","graph_spreading","entity_semantic_edges","l0","l1","l2","l3","l4"],"title":"MemoryConfigModel","type":"object"};
const schema40 = {"properties":{"local":{"$ref":"#/components/schemas/EmbeddingLocalConfigModel"},"mode":{"default":"remote","title":"Mode","type":"string"}},"required":["mode","local"],"title":"EmbeddingConfigModel","type":"object"};
const schema41 = {"properties":{"idle_timeout_seconds":{"default":1800,"minimum":60,"title":"Idle Timeout Seconds","type":"integer"},"managed_model_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Managed Model Id"},"model_dir_path":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Model Dir Path"},"model_source":{"default":"managed","title":"Model Source","type":"string"},"variant":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Variant"}},"required":["model_source","managed_model_id","model_dir_path","idle_timeout_seconds","variant"],"title":"EmbeddingLocalConfigModel","type":"object"};

function validate92(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate92.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((data.model_source === undefined) && (missing0 = "model_source")) || ((data.managed_model_id === undefined) && (missing0 = "managed_model_id"))) || ((data.model_dir_path === undefined) && (missing0 = "model_dir_path"))) || ((data.idle_timeout_seconds === undefined) && (missing0 = "idle_timeout_seconds"))) || ((data.variant === undefined) && (missing0 = "variant"))){
validate92.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.idle_timeout_seconds !== undefined){
let data0 = data.idle_timeout_seconds;
const _errs1 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate92.errors = [{instancePath:instancePath+"/idle_timeout_seconds",schemaPath:"#/properties/idle_timeout_seconds/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs1){
if(typeof data0 == "number"){
if(data0 < 60 || isNaN(data0)){
validate92.errors = [{instancePath:instancePath+"/idle_timeout_seconds",schemaPath:"#/properties/idle_timeout_seconds/minimum",keyword:"minimum",params:{comparison: ">=", limit: 60},message:"must be >= 60"}];
return false;
}
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.managed_model_id !== undefined){
let data1 = data.managed_model_id;
const _errs3 = errors;
const _errs4 = errors;
let valid1 = false;
const _errs5 = errors;
if(typeof data1 !== "string"){
const err0 = {instancePath:instancePath+"/managed_model_id",schemaPath:"#/properties/managed_model_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs5 === errors;
valid1 = valid1 || _valid0;
const _errs7 = errors;
if(data1 !== null){
const err1 = {instancePath:instancePath+"/managed_model_id",schemaPath:"#/properties/managed_model_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs7 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/managed_model_id",schemaPath:"#/properties/managed_model_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate92.errors = vErrors;
return false;
}
else {
errors = _errs4;
if(vErrors !== null){
if(_errs4){
vErrors.length = _errs4;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.model_dir_path !== undefined){
let data2 = data.model_dir_path;
const _errs9 = errors;
const _errs10 = errors;
let valid2 = false;
const _errs11 = errors;
if(typeof data2 !== "string"){
const err3 = {instancePath:instancePath+"/model_dir_path",schemaPath:"#/properties/model_dir_path/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs11 === errors;
valid2 = valid2 || _valid1;
const _errs13 = errors;
if(data2 !== null){
const err4 = {instancePath:instancePath+"/model_dir_path",schemaPath:"#/properties/model_dir_path/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs13 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err5 = {instancePath:instancePath+"/model_dir_path",schemaPath:"#/properties/model_dir_path/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate92.errors = vErrors;
return false;
}
else {
errors = _errs10;
if(vErrors !== null){
if(_errs10){
vErrors.length = _errs10;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.model_source !== undefined){
const _errs15 = errors;
if(typeof data.model_source !== "string"){
validate92.errors = [{instancePath:instancePath+"/model_source",schemaPath:"#/properties/model_source/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs15 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.variant !== undefined){
let data4 = data.variant;
const _errs17 = errors;
const _errs18 = errors;
let valid3 = false;
const _errs19 = errors;
if(typeof data4 !== "string"){
const err6 = {instancePath:instancePath+"/variant",schemaPath:"#/properties/variant/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid2 = _errs19 === errors;
valid3 = valid3 || _valid2;
const _errs21 = errors;
if(data4 !== null){
const err7 = {instancePath:instancePath+"/variant",schemaPath:"#/properties/variant/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
}
var _valid2 = _errs21 === errors;
valid3 = valid3 || _valid2;
if(!valid3){
const err8 = {instancePath:instancePath+"/variant",schemaPath:"#/properties/variant/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
validate92.errors = vErrors;
return false;
}
else {
errors = _errs18;
if(vErrors !== null){
if(_errs18){
vErrors.length = _errs18;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs17 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
else {
validate92.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate92.errors = vErrors;
return errors === 0;
}
validate92.evaluated = {"props":{"idle_timeout_seconds":true,"managed_model_id":true,"model_dir_path":true,"model_source":true,"variant":true},"dynamicProps":false,"dynamicItems":false};


function validate91(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate91.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((data.mode === undefined) && (missing0 = "mode")) || ((data.local === undefined) && (missing0 = "local"))){
validate91.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.local !== undefined){
const _errs1 = errors;
if(!(validate92(data.local, {instancePath:instancePath+"/local",parentData:data,parentDataProperty:"local",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate92.errors : vErrors.concat(validate92.errors);
errors = vErrors.length;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.mode !== undefined){
const _errs2 = errors;
if(typeof data.mode !== "string"){
validate91.errors = [{instancePath:instancePath+"/mode",schemaPath:"#/properties/mode/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
}
}
}
else {
validate91.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate91.errors = vErrors;
return errors === 0;
}
validate91.evaluated = {"props":{"local":true,"mode":true},"dynamicProps":false,"dynamicItems":false};

const schema42 = {"properties":{"enabled":{"default":false,"title":"Enabled","type":"boolean"}},"required":["enabled"],"title":"EntitySemanticEdgeConfigModel","type":"object"};

function validate95(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate95.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((data.enabled === undefined) && (missing0 = "enabled")){
validate95.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.enabled !== undefined){
if(typeof data.enabled !== "boolean"){
validate95.errors = [{instancePath:instancePath+"/enabled",schemaPath:"#/properties/enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
}
}
}
else {
validate95.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate95.errors = vErrors;
return errors === 0;
}
validate95.evaluated = {"props":{"enabled":true},"dynamicProps":false,"dynamicItems":false};

const schema43 = {"properties":{"enabled":{"default":true,"title":"Enabled","type":"boolean"}},"required":["enabled"],"title":"GraphSpreadingConfigModel","type":"object"};

function validate97(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate97.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((data.enabled === undefined) && (missing0 = "enabled")){
validate97.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.enabled !== undefined){
if(typeof data.enabled !== "boolean"){
validate97.errors = [{instancePath:instancePath+"/enabled",schemaPath:"#/properties/enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
}
}
}
else {
validate97.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate97.errors = vErrors;
return errors === 0;
}
validate97.evaluated = {"props":{"enabled":true},"dynamicProps":false,"dynamicItems":false};

const schema44 = {"properties":{"attention_update_idle_seconds":{"default":30,"maximum":300,"minimum":1,"title":"Attention Update Idle Seconds","type":"integer"},"attention_update_max_delay_seconds":{"default":90,"maximum":600,"minimum":1,"title":"Attention Update Max Delay Seconds","type":"integer"},"attention_update_turn_threshold":{"default":3,"maximum":20,"minimum":1,"title":"Attention Update Turn Threshold","type":"integer"},"checkpoint_interval_seconds":{"default":30,"minimum":1,"title":"Checkpoint Interval Seconds","type":"integer"},"enabled":{"default":true,"title":"Enabled","type":"boolean"}},"required":["enabled","checkpoint_interval_seconds","attention_update_turn_threshold","attention_update_idle_seconds","attention_update_max_delay_seconds"],"title":"MemoryL0ConfigModel","type":"object"};

function validate99(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate99.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((data.enabled === undefined) && (missing0 = "enabled")) || ((data.checkpoint_interval_seconds === undefined) && (missing0 = "checkpoint_interval_seconds"))) || ((data.attention_update_turn_threshold === undefined) && (missing0 = "attention_update_turn_threshold"))) || ((data.attention_update_idle_seconds === undefined) && (missing0 = "attention_update_idle_seconds"))) || ((data.attention_update_max_delay_seconds === undefined) && (missing0 = "attention_update_max_delay_seconds"))){
validate99.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.attention_update_idle_seconds !== undefined){
let data0 = data.attention_update_idle_seconds;
const _errs1 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate99.errors = [{instancePath:instancePath+"/attention_update_idle_seconds",schemaPath:"#/properties/attention_update_idle_seconds/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs1){
if(typeof data0 == "number"){
if(data0 > 300 || isNaN(data0)){
validate99.errors = [{instancePath:instancePath+"/attention_update_idle_seconds",schemaPath:"#/properties/attention_update_idle_seconds/maximum",keyword:"maximum",params:{comparison: "<=", limit: 300},message:"must be <= 300"}];
return false;
}
else {
if(data0 < 1 || isNaN(data0)){
validate99.errors = [{instancePath:instancePath+"/attention_update_idle_seconds",schemaPath:"#/properties/attention_update_idle_seconds/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"}];
return false;
}
}
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.attention_update_max_delay_seconds !== undefined){
let data1 = data.attention_update_max_delay_seconds;
const _errs3 = errors;
if(!((typeof data1 == "number") && (!(data1 % 1) && !isNaN(data1)))){
validate99.errors = [{instancePath:instancePath+"/attention_update_max_delay_seconds",schemaPath:"#/properties/attention_update_max_delay_seconds/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs3){
if(typeof data1 == "number"){
if(data1 > 600 || isNaN(data1)){
validate99.errors = [{instancePath:instancePath+"/attention_update_max_delay_seconds",schemaPath:"#/properties/attention_update_max_delay_seconds/maximum",keyword:"maximum",params:{comparison: "<=", limit: 600},message:"must be <= 600"}];
return false;
}
else {
if(data1 < 1 || isNaN(data1)){
validate99.errors = [{instancePath:instancePath+"/attention_update_max_delay_seconds",schemaPath:"#/properties/attention_update_max_delay_seconds/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"}];
return false;
}
}
}
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.attention_update_turn_threshold !== undefined){
let data2 = data.attention_update_turn_threshold;
const _errs5 = errors;
if(!((typeof data2 == "number") && (!(data2 % 1) && !isNaN(data2)))){
validate99.errors = [{instancePath:instancePath+"/attention_update_turn_threshold",schemaPath:"#/properties/attention_update_turn_threshold/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs5){
if(typeof data2 == "number"){
if(data2 > 20 || isNaN(data2)){
validate99.errors = [{instancePath:instancePath+"/attention_update_turn_threshold",schemaPath:"#/properties/attention_update_turn_threshold/maximum",keyword:"maximum",params:{comparison: "<=", limit: 20},message:"must be <= 20"}];
return false;
}
else {
if(data2 < 1 || isNaN(data2)){
validate99.errors = [{instancePath:instancePath+"/attention_update_turn_threshold",schemaPath:"#/properties/attention_update_turn_threshold/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"}];
return false;
}
}
}
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.checkpoint_interval_seconds !== undefined){
let data3 = data.checkpoint_interval_seconds;
const _errs7 = errors;
if(!((typeof data3 == "number") && (!(data3 % 1) && !isNaN(data3)))){
validate99.errors = [{instancePath:instancePath+"/checkpoint_interval_seconds",schemaPath:"#/properties/checkpoint_interval_seconds/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs7){
if(typeof data3 == "number"){
if(data3 < 1 || isNaN(data3)){
validate99.errors = [{instancePath:instancePath+"/checkpoint_interval_seconds",schemaPath:"#/properties/checkpoint_interval_seconds/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"}];
return false;
}
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.enabled !== undefined){
const _errs9 = errors;
if(typeof data.enabled !== "boolean"){
validate99.errors = [{instancePath:instancePath+"/enabled",schemaPath:"#/properties/enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
else {
validate99.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate99.errors = vErrors;
return errors === 0;
}
validate99.evaluated = {"props":{"attention_update_idle_seconds":true,"attention_update_max_delay_seconds":true,"attention_update_turn_threshold":true,"checkpoint_interval_seconds":true,"enabled":true},"dynamicProps":false,"dynamicItems":false};

const schema45 = {"properties":{"enabled":{"default":true,"title":"Enabled","type":"boolean"},"retention_days":{"default":30,"minimum":1,"title":"Retention Days","type":"integer"},"vectors_enabled":{"default":true,"title":"Vectors Enabled","type":"boolean"}},"required":["enabled","retention_days","vectors_enabled"],"title":"MemoryL1ConfigModel","type":"object"};

function validate101(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate101.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((data.enabled === undefined) && (missing0 = "enabled")) || ((data.retention_days === undefined) && (missing0 = "retention_days"))) || ((data.vectors_enabled === undefined) && (missing0 = "vectors_enabled"))){
validate101.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.enabled !== undefined){
const _errs1 = errors;
if(typeof data.enabled !== "boolean"){
validate101.errors = [{instancePath:instancePath+"/enabled",schemaPath:"#/properties/enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.retention_days !== undefined){
let data1 = data.retention_days;
const _errs3 = errors;
if(!((typeof data1 == "number") && (!(data1 % 1) && !isNaN(data1)))){
validate101.errors = [{instancePath:instancePath+"/retention_days",schemaPath:"#/properties/retention_days/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs3){
if(typeof data1 == "number"){
if(data1 < 1 || isNaN(data1)){
validate101.errors = [{instancePath:instancePath+"/retention_days",schemaPath:"#/properties/retention_days/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"}];
return false;
}
}
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.vectors_enabled !== undefined){
const _errs5 = errors;
if(typeof data.vectors_enabled !== "boolean"){
validate101.errors = [{instancePath:instancePath+"/vectors_enabled",schemaPath:"#/properties/vectors_enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
else {
validate101.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate101.errors = vErrors;
return errors === 0;
}
validate101.evaluated = {"props":{"enabled":true,"retention_days":true,"vectors_enabled":true},"dynamicProps":false,"dynamicItems":false};

const schema46 = {"properties":{"auto_extract_relations":{"default":true,"title":"Auto Extract Relations","type":"boolean"},"batch_flush_interval_seconds":{"default":60,"minimum":30,"title":"Batch Flush Interval Seconds","type":"integer"},"enabled":{"default":true,"title":"Enabled","type":"boolean"},"portrait_projection_refresh_delay_seconds":{"default":120,"minimum":0,"title":"Portrait Projection Refresh Delay Seconds","type":"number"},"shadow_conflict_notification_enabled":{"default":true,"title":"Shadow Conflict Notification Enabled","type":"boolean"},"vectors_enabled":{"default":true,"title":"Vectors Enabled","type":"boolean"}},"required":["enabled","vectors_enabled","batch_flush_interval_seconds","auto_extract_relations","shadow_conflict_notification_enabled","portrait_projection_refresh_delay_seconds"],"title":"MemoryL2ConfigModel","type":"object"};

function validate103(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate103.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((data.enabled === undefined) && (missing0 = "enabled")) || ((data.vectors_enabled === undefined) && (missing0 = "vectors_enabled"))) || ((data.batch_flush_interval_seconds === undefined) && (missing0 = "batch_flush_interval_seconds"))) || ((data.auto_extract_relations === undefined) && (missing0 = "auto_extract_relations"))) || ((data.shadow_conflict_notification_enabled === undefined) && (missing0 = "shadow_conflict_notification_enabled"))) || ((data.portrait_projection_refresh_delay_seconds === undefined) && (missing0 = "portrait_projection_refresh_delay_seconds"))){
validate103.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.auto_extract_relations !== undefined){
const _errs1 = errors;
if(typeof data.auto_extract_relations !== "boolean"){
validate103.errors = [{instancePath:instancePath+"/auto_extract_relations",schemaPath:"#/properties/auto_extract_relations/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.batch_flush_interval_seconds !== undefined){
let data1 = data.batch_flush_interval_seconds;
const _errs3 = errors;
if(!((typeof data1 == "number") && (!(data1 % 1) && !isNaN(data1)))){
validate103.errors = [{instancePath:instancePath+"/batch_flush_interval_seconds",schemaPath:"#/properties/batch_flush_interval_seconds/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs3){
if(typeof data1 == "number"){
if(data1 < 30 || isNaN(data1)){
validate103.errors = [{instancePath:instancePath+"/batch_flush_interval_seconds",schemaPath:"#/properties/batch_flush_interval_seconds/minimum",keyword:"minimum",params:{comparison: ">=", limit: 30},message:"must be >= 30"}];
return false;
}
}
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.enabled !== undefined){
const _errs5 = errors;
if(typeof data.enabled !== "boolean"){
validate103.errors = [{instancePath:instancePath+"/enabled",schemaPath:"#/properties/enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.portrait_projection_refresh_delay_seconds !== undefined){
let data3 = data.portrait_projection_refresh_delay_seconds;
const _errs7 = errors;
if(errors === _errs7){
if(typeof data3 == "number"){
if(data3 < 0 || isNaN(data3)){
validate103.errors = [{instancePath:instancePath+"/portrait_projection_refresh_delay_seconds",schemaPath:"#/properties/portrait_projection_refresh_delay_seconds/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
else {
validate103.errors = [{instancePath:instancePath+"/portrait_projection_refresh_delay_seconds",schemaPath:"#/properties/portrait_projection_refresh_delay_seconds/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.shadow_conflict_notification_enabled !== undefined){
const _errs9 = errors;
if(typeof data.shadow_conflict_notification_enabled !== "boolean"){
validate103.errors = [{instancePath:instancePath+"/shadow_conflict_notification_enabled",schemaPath:"#/properties/shadow_conflict_notification_enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.vectors_enabled !== undefined){
const _errs11 = errors;
if(typeof data.vectors_enabled !== "boolean"){
validate103.errors = [{instancePath:instancePath+"/vectors_enabled",schemaPath:"#/properties/vectors_enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
else {
validate103.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate103.errors = vErrors;
return errors === 0;
}
validate103.evaluated = {"props":{"auto_extract_relations":true,"batch_flush_interval_seconds":true,"enabled":true,"portrait_projection_refresh_delay_seconds":true,"shadow_conflict_notification_enabled":true,"vectors_enabled":true},"dynamicProps":false,"dynamicItems":false};

const schema47 = {"additionalProperties":false,"properties":{"enabled":{"default":true,"title":"Enabled","type":"boolean"},"llm_summary_enabled":{"default":true,"title":"Llm Summary Enabled","type":"boolean"},"retention_days":{"default":180,"minimum":1,"title":"Retention Days","type":"integer"},"temporal_llm_min_event_count":{"default":2,"minimum":1,"title":"Temporal Llm Min Event Count","type":"integer"},"temporal_llm_timeout_seconds":{"default":3,"minimum":0.1,"title":"Temporal Llm Timeout Seconds","type":"number"},"vectors_enabled":{"default":true,"title":"Vectors Enabled","type":"boolean"}},"required":["enabled","retention_days","vectors_enabled","llm_summary_enabled","temporal_llm_timeout_seconds","temporal_llm_min_event_count"],"title":"MemoryL3ConfigModel","type":"object"};

function validate105(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate105.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((data.enabled === undefined) && (missing0 = "enabled")) || ((data.retention_days === undefined) && (missing0 = "retention_days"))) || ((data.vectors_enabled === undefined) && (missing0 = "vectors_enabled"))) || ((data.llm_summary_enabled === undefined) && (missing0 = "llm_summary_enabled"))) || ((data.temporal_llm_timeout_seconds === undefined) && (missing0 = "temporal_llm_timeout_seconds"))) || ((data.temporal_llm_min_event_count === undefined) && (missing0 = "temporal_llm_min_event_count"))){
validate105.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!((((((key0 === "enabled") || (key0 === "llm_summary_enabled")) || (key0 === "retention_days")) || (key0 === "temporal_llm_min_event_count")) || (key0 === "temporal_llm_timeout_seconds")) || (key0 === "vectors_enabled"))){
validate105.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.enabled !== undefined){
const _errs2 = errors;
if(typeof data.enabled !== "boolean"){
validate105.errors = [{instancePath:instancePath+"/enabled",schemaPath:"#/properties/enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.llm_summary_enabled !== undefined){
const _errs4 = errors;
if(typeof data.llm_summary_enabled !== "boolean"){
validate105.errors = [{instancePath:instancePath+"/llm_summary_enabled",schemaPath:"#/properties/llm_summary_enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.retention_days !== undefined){
let data2 = data.retention_days;
const _errs6 = errors;
if(!((typeof data2 == "number") && (!(data2 % 1) && !isNaN(data2)))){
validate105.errors = [{instancePath:instancePath+"/retention_days",schemaPath:"#/properties/retention_days/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs6){
if(typeof data2 == "number"){
if(data2 < 1 || isNaN(data2)){
validate105.errors = [{instancePath:instancePath+"/retention_days",schemaPath:"#/properties/retention_days/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"}];
return false;
}
}
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.temporal_llm_min_event_count !== undefined){
let data3 = data.temporal_llm_min_event_count;
const _errs8 = errors;
if(!((typeof data3 == "number") && (!(data3 % 1) && !isNaN(data3)))){
validate105.errors = [{instancePath:instancePath+"/temporal_llm_min_event_count",schemaPath:"#/properties/temporal_llm_min_event_count/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs8){
if(typeof data3 == "number"){
if(data3 < 1 || isNaN(data3)){
validate105.errors = [{instancePath:instancePath+"/temporal_llm_min_event_count",schemaPath:"#/properties/temporal_llm_min_event_count/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"}];
return false;
}
}
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.temporal_llm_timeout_seconds !== undefined){
let data4 = data.temporal_llm_timeout_seconds;
const _errs10 = errors;
if(errors === _errs10){
if(typeof data4 == "number"){
if(data4 < 0.1 || isNaN(data4)){
validate105.errors = [{instancePath:instancePath+"/temporal_llm_timeout_seconds",schemaPath:"#/properties/temporal_llm_timeout_seconds/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0.1},message:"must be >= 0.1"}];
return false;
}
}
else {
validate105.errors = [{instancePath:instancePath+"/temporal_llm_timeout_seconds",schemaPath:"#/properties/temporal_llm_timeout_seconds/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
}
var valid0 = _errs10 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.vectors_enabled !== undefined){
const _errs12 = errors;
if(typeof data.vectors_enabled !== "boolean"){
validate105.errors = [{instancePath:instancePath+"/vectors_enabled",schemaPath:"#/properties/vectors_enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
else {
validate105.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate105.errors = vErrors;
return errors === 0;
}
validate105.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

const schema48 = {"properties":{"enabled":{"default":true,"title":"Enabled","type":"boolean"},"inactive_skill_min_attempts":{"default":5,"minimum":1,"title":"Inactive Skill Min Attempts","type":"integer"},"inactive_skill_retention_days":{"default":30,"minimum":1,"title":"Inactive Skill Retention Days","type":"integer"},"vectors_enabled":{"default":true,"title":"Vectors Enabled","type":"boolean"}},"required":["enabled","vectors_enabled","inactive_skill_retention_days","inactive_skill_min_attempts"],"title":"MemoryL4ConfigModel","type":"object"};

function validate107(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate107.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((data.enabled === undefined) && (missing0 = "enabled")) || ((data.vectors_enabled === undefined) && (missing0 = "vectors_enabled"))) || ((data.inactive_skill_retention_days === undefined) && (missing0 = "inactive_skill_retention_days"))) || ((data.inactive_skill_min_attempts === undefined) && (missing0 = "inactive_skill_min_attempts"))){
validate107.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.enabled !== undefined){
const _errs1 = errors;
if(typeof data.enabled !== "boolean"){
validate107.errors = [{instancePath:instancePath+"/enabled",schemaPath:"#/properties/enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.inactive_skill_min_attempts !== undefined){
let data1 = data.inactive_skill_min_attempts;
const _errs3 = errors;
if(!((typeof data1 == "number") && (!(data1 % 1) && !isNaN(data1)))){
validate107.errors = [{instancePath:instancePath+"/inactive_skill_min_attempts",schemaPath:"#/properties/inactive_skill_min_attempts/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs3){
if(typeof data1 == "number"){
if(data1 < 1 || isNaN(data1)){
validate107.errors = [{instancePath:instancePath+"/inactive_skill_min_attempts",schemaPath:"#/properties/inactive_skill_min_attempts/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"}];
return false;
}
}
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.inactive_skill_retention_days !== undefined){
let data2 = data.inactive_skill_retention_days;
const _errs5 = errors;
if(!((typeof data2 == "number") && (!(data2 % 1) && !isNaN(data2)))){
validate107.errors = [{instancePath:instancePath+"/inactive_skill_retention_days",schemaPath:"#/properties/inactive_skill_retention_days/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs5){
if(typeof data2 == "number"){
if(data2 < 1 || isNaN(data2)){
validate107.errors = [{instancePath:instancePath+"/inactive_skill_retention_days",schemaPath:"#/properties/inactive_skill_retention_days/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"}];
return false;
}
}
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.vectors_enabled !== undefined){
const _errs7 = errors;
if(typeof data.vectors_enabled !== "boolean"){
validate107.errors = [{instancePath:instancePath+"/vectors_enabled",schemaPath:"#/properties/vectors_enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
else {
validate107.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate107.errors = vErrors;
return errors === 0;
}
validate107.evaluated = {"props":{"enabled":true,"inactive_skill_min_attempts":true,"inactive_skill_retention_days":true,"vectors_enabled":true},"dynamicProps":false,"dynamicItems":false};

const schema49 = {"properties":{"enabled":{"default":true,"title":"Enabled","type":"boolean"},"max_expansions":{"default":2,"maximum":5,"minimum":1,"title":"Max Expansions","type":"integer"}},"required":["enabled","max_expansions"],"title":"QueryExpansionConfigModel","type":"object"};

function validate109(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate109.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((data.enabled === undefined) && (missing0 = "enabled")) || ((data.max_expansions === undefined) && (missing0 = "max_expansions"))){
validate109.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.enabled !== undefined){
const _errs1 = errors;
if(typeof data.enabled !== "boolean"){
validate109.errors = [{instancePath:instancePath+"/enabled",schemaPath:"#/properties/enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.max_expansions !== undefined){
let data1 = data.max_expansions;
const _errs3 = errors;
if(!((typeof data1 == "number") && (!(data1 % 1) && !isNaN(data1)))){
validate109.errors = [{instancePath:instancePath+"/max_expansions",schemaPath:"#/properties/max_expansions/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs3){
if(typeof data1 == "number"){
if(data1 > 5 || isNaN(data1)){
validate109.errors = [{instancePath:instancePath+"/max_expansions",schemaPath:"#/properties/max_expansions/maximum",keyword:"maximum",params:{comparison: "<=", limit: 5},message:"must be <= 5"}];
return false;
}
else {
if(data1 < 1 || isNaN(data1)){
validate109.errors = [{instancePath:instancePath+"/max_expansions",schemaPath:"#/properties/max_expansions/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"}];
return false;
}
}
}
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
}
}
}
else {
validate109.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate109.errors = vErrors;
return errors === 0;
}
validate109.evaluated = {"props":{"enabled":true,"max_expansions":true},"dynamicProps":false,"dynamicItems":false};

const schema50 = {"properties":{"cross_encoder":{"$ref":"#/components/schemas/CrossEncoderConfigModel"},"top_k":{"default":8,"minimum":1,"title":"Top K","type":"integer"}},"required":["top_k","cross_encoder"],"title":"MemoryRerankerConfigModel","type":"object"};
const schema51 = {"properties":{"enabled":{"default":false,"title":"Enabled","type":"boolean"},"managed_model_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Managed Model Id"}},"required":["enabled","managed_model_id"],"title":"CrossEncoderConfigModel","type":"object"};

function validate112(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate112.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((data.enabled === undefined) && (missing0 = "enabled")) || ((data.managed_model_id === undefined) && (missing0 = "managed_model_id"))){
validate112.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.enabled !== undefined){
const _errs1 = errors;
if(typeof data.enabled !== "boolean"){
validate112.errors = [{instancePath:instancePath+"/enabled",schemaPath:"#/properties/enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.managed_model_id !== undefined){
let data1 = data.managed_model_id;
const _errs3 = errors;
const _errs4 = errors;
let valid1 = false;
const _errs5 = errors;
if(typeof data1 !== "string"){
const err0 = {instancePath:instancePath+"/managed_model_id",schemaPath:"#/properties/managed_model_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs5 === errors;
valid1 = valid1 || _valid0;
const _errs7 = errors;
if(data1 !== null){
const err1 = {instancePath:instancePath+"/managed_model_id",schemaPath:"#/properties/managed_model_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs7 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/managed_model_id",schemaPath:"#/properties/managed_model_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate112.errors = vErrors;
return false;
}
else {
errors = _errs4;
if(vErrors !== null){
if(_errs4){
vErrors.length = _errs4;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
}
}
}
else {
validate112.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate112.errors = vErrors;
return errors === 0;
}
validate112.evaluated = {"props":{"enabled":true,"managed_model_id":true},"dynamicProps":false,"dynamicItems":false};


function validate111(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate111.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((data.top_k === undefined) && (missing0 = "top_k")) || ((data.cross_encoder === undefined) && (missing0 = "cross_encoder"))){
validate111.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.cross_encoder !== undefined){
const _errs1 = errors;
if(!(validate112(data.cross_encoder, {instancePath:instancePath+"/cross_encoder",parentData:data,parentDataProperty:"cross_encoder",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate112.errors : vErrors.concat(validate112.errors);
errors = vErrors.length;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.top_k !== undefined){
let data1 = data.top_k;
const _errs2 = errors;
if(!((typeof data1 == "number") && (!(data1 % 1) && !isNaN(data1)))){
validate111.errors = [{instancePath:instancePath+"/top_k",schemaPath:"#/properties/top_k/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs2){
if(typeof data1 == "number"){
if(data1 < 1 || isNaN(data1)){
validate111.errors = [{instancePath:instancePath+"/top_k",schemaPath:"#/properties/top_k/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"}];
return false;
}
}
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
}
}
}
else {
validate111.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate111.errors = vErrors;
return errors === 0;
}
validate111.evaluated = {"props":{"cross_encoder":true,"top_k":true},"dynamicProps":false,"dynamicItems":false};


function validate90(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate90.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((((((((((data.db_path === undefined) && (missing0 = "db_path")) || ((data.retention_days === undefined) && (missing0 = "retention_days"))) || ((data.history_behavior === undefined) && (missing0 = "history_behavior"))) || ((data.archive_path === undefined) && (missing0 = "archive_path"))) || ((data.embedding === undefined) && (missing0 = "embedding"))) || ((data.reranker === undefined) && (missing0 = "reranker"))) || ((data.query_expansion === undefined) && (missing0 = "query_expansion"))) || ((data.graph_spreading === undefined) && (missing0 = "graph_spreading"))) || ((data.entity_semantic_edges === undefined) && (missing0 = "entity_semantic_edges"))) || ((data.l0 === undefined) && (missing0 = "l0"))) || ((data.l1 === undefined) && (missing0 = "l1"))) || ((data.l2 === undefined) && (missing0 = "l2"))) || ((data.l3 === undefined) && (missing0 = "l3"))) || ((data.l4 === undefined) && (missing0 = "l4"))){
validate90.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.archive_path !== undefined){
let data0 = data.archive_path;
const _errs1 = errors;
const _errs2 = errors;
let valid1 = false;
const _errs3 = errors;
if(typeof data0 !== "string"){
const err0 = {instancePath:instancePath+"/archive_path",schemaPath:"#/properties/archive_path/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs3 === errors;
valid1 = valid1 || _valid0;
const _errs5 = errors;
if(data0 !== null){
const err1 = {instancePath:instancePath+"/archive_path",schemaPath:"#/properties/archive_path/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs5 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/archive_path",schemaPath:"#/properties/archive_path/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate90.errors = vErrors;
return false;
}
else {
errors = _errs2;
if(vErrors !== null){
if(_errs2){
vErrors.length = _errs2;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.db_path !== undefined){
let data1 = data.db_path;
const _errs7 = errors;
const _errs8 = errors;
let valid2 = false;
const _errs9 = errors;
if(typeof data1 !== "string"){
const err3 = {instancePath:instancePath+"/db_path",schemaPath:"#/properties/db_path/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs9 === errors;
valid2 = valid2 || _valid1;
const _errs11 = errors;
if(data1 !== null){
const err4 = {instancePath:instancePath+"/db_path",schemaPath:"#/properties/db_path/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs11 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err5 = {instancePath:instancePath+"/db_path",schemaPath:"#/properties/db_path/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate90.errors = vErrors;
return false;
}
else {
errors = _errs8;
if(vErrors !== null){
if(_errs8){
vErrors.length = _errs8;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.embedding !== undefined){
const _errs13 = errors;
if(!(validate91(data.embedding, {instancePath:instancePath+"/embedding",parentData:data,parentDataProperty:"embedding",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate91.errors : vErrors.concat(validate91.errors);
errors = vErrors.length;
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.entity_semantic_edges !== undefined){
const _errs14 = errors;
if(!(validate95(data.entity_semantic_edges, {instancePath:instancePath+"/entity_semantic_edges",parentData:data,parentDataProperty:"entity_semantic_edges",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate95.errors : vErrors.concat(validate95.errors);
errors = vErrors.length;
}
var valid0 = _errs14 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.graph_spreading !== undefined){
const _errs15 = errors;
if(!(validate97(data.graph_spreading, {instancePath:instancePath+"/graph_spreading",parentData:data,parentDataProperty:"graph_spreading",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate97.errors : vErrors.concat(validate97.errors);
errors = vErrors.length;
}
var valid0 = _errs15 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.history_behavior !== undefined){
const _errs16 = errors;
if(typeof data.history_behavior !== "string"){
validate90.errors = [{instancePath:instancePath+"/history_behavior",schemaPath:"#/properties/history_behavior/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs16 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.l0 !== undefined){
const _errs18 = errors;
if(!(validate99(data.l0, {instancePath:instancePath+"/l0",parentData:data,parentDataProperty:"l0",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate99.errors : vErrors.concat(validate99.errors);
errors = vErrors.length;
}
var valid0 = _errs18 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.l1 !== undefined){
const _errs19 = errors;
if(!(validate101(data.l1, {instancePath:instancePath+"/l1",parentData:data,parentDataProperty:"l1",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate101.errors : vErrors.concat(validate101.errors);
errors = vErrors.length;
}
var valid0 = _errs19 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.l2 !== undefined){
const _errs20 = errors;
if(!(validate103(data.l2, {instancePath:instancePath+"/l2",parentData:data,parentDataProperty:"l2",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate103.errors : vErrors.concat(validate103.errors);
errors = vErrors.length;
}
var valid0 = _errs20 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.l3 !== undefined){
const _errs21 = errors;
if(!(validate105(data.l3, {instancePath:instancePath+"/l3",parentData:data,parentDataProperty:"l3",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate105.errors : vErrors.concat(validate105.errors);
errors = vErrors.length;
}
var valid0 = _errs21 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.l4 !== undefined){
const _errs22 = errors;
if(!(validate107(data.l4, {instancePath:instancePath+"/l4",parentData:data,parentDataProperty:"l4",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate107.errors : vErrors.concat(validate107.errors);
errors = vErrors.length;
}
var valid0 = _errs22 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.query_expansion !== undefined){
const _errs23 = errors;
if(!(validate109(data.query_expansion, {instancePath:instancePath+"/query_expansion",parentData:data,parentDataProperty:"query_expansion",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate109.errors : vErrors.concat(validate109.errors);
errors = vErrors.length;
}
var valid0 = _errs23 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.reranker !== undefined){
const _errs24 = errors;
if(!(validate111(data.reranker, {instancePath:instancePath+"/reranker",parentData:data,parentDataProperty:"reranker",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate111.errors : vErrors.concat(validate111.errors);
errors = vErrors.length;
}
var valid0 = _errs24 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.retention_days !== undefined){
let data13 = data.retention_days;
const _errs25 = errors;
if(!((typeof data13 == "number") && (!(data13 % 1) && !isNaN(data13)))){
validate90.errors = [{instancePath:instancePath+"/retention_days",schemaPath:"#/properties/retention_days/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs25){
if(typeof data13 == "number"){
if(data13 < 1 || isNaN(data13)){
validate90.errors = [{instancePath:instancePath+"/retention_days",schemaPath:"#/properties/retention_days/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"}];
return false;
}
}
}
var valid0 = _errs25 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
else {
validate90.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate90.errors = vErrors;
return errors === 0;
}
validate90.evaluated = {"props":{"archive_path":true,"db_path":true,"embedding":true,"entity_semantic_edges":true,"graph_spreading":true,"history_behavior":true,"l0":true,"l1":true,"l2":true,"l3":true,"l4":true,"query_expansion":true,"reranker":true,"retention_days":true},"dynamicProps":false,"dynamicItems":false};

const schema52 = {"properties":{"enabled":{"default":false,"title":"Enabled","type":"boolean"},"host":{"default":"127.0.0.1","title":"Host","type":"string"},"password":{"default":"","title":"Password","type":"string"},"port":{"default":7890,"maximum":65535,"minimum":1,"title":"Port","type":"integer"},"proxy_type":{"default":"http","title":"Proxy Type","type":"string"},"username":{"default":"","title":"Username","type":"string"}},"required":["enabled","proxy_type","host","port","username","password"],"title":"NetworkProxyConfigModel","type":"object"};

function validate116(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate116.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((data.enabled === undefined) && (missing0 = "enabled")) || ((data.proxy_type === undefined) && (missing0 = "proxy_type"))) || ((data.host === undefined) && (missing0 = "host"))) || ((data.port === undefined) && (missing0 = "port"))) || ((data.username === undefined) && (missing0 = "username"))) || ((data.password === undefined) && (missing0 = "password"))){
validate116.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.enabled !== undefined){
const _errs1 = errors;
if(typeof data.enabled !== "boolean"){
validate116.errors = [{instancePath:instancePath+"/enabled",schemaPath:"#/properties/enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.host !== undefined){
const _errs3 = errors;
if(typeof data.host !== "string"){
validate116.errors = [{instancePath:instancePath+"/host",schemaPath:"#/properties/host/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.password !== undefined){
const _errs5 = errors;
if(typeof data.password !== "string"){
validate116.errors = [{instancePath:instancePath+"/password",schemaPath:"#/properties/password/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.port !== undefined){
let data3 = data.port;
const _errs7 = errors;
if(!((typeof data3 == "number") && (!(data3 % 1) && !isNaN(data3)))){
validate116.errors = [{instancePath:instancePath+"/port",schemaPath:"#/properties/port/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs7){
if(typeof data3 == "number"){
if(data3 > 65535 || isNaN(data3)){
validate116.errors = [{instancePath:instancePath+"/port",schemaPath:"#/properties/port/maximum",keyword:"maximum",params:{comparison: "<=", limit: 65535},message:"must be <= 65535"}];
return false;
}
else {
if(data3 < 1 || isNaN(data3)){
validate116.errors = [{instancePath:instancePath+"/port",schemaPath:"#/properties/port/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"}];
return false;
}
}
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.proxy_type !== undefined){
const _errs9 = errors;
if(typeof data.proxy_type !== "string"){
validate116.errors = [{instancePath:instancePath+"/proxy_type",schemaPath:"#/properties/proxy_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.username !== undefined){
const _errs11 = errors;
if(typeof data.username !== "string"){
validate116.errors = [{instancePath:instancePath+"/username",schemaPath:"#/properties/username/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
else {
validate116.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate116.errors = vErrors;
return errors === 0;
}
validate116.evaluated = {"props":{"enabled":true,"host":true,"password":true,"port":true,"proxy_type":true,"username":true},"dynamicProps":false,"dynamicItems":false};

const schema53 = {"properties":{"appearance_prompt":{"default":"","title":"Appearance Prompt","type":"string"},"avatar":{"default":"","title":"Avatar","type":"string"},"bootstrap":{"anyOf":[{"$ref":"#/components/schemas/BootstrapConfigModel"},{"type":"null"}],"default":null},"description":{"default":"","title":"Description","type":"string"},"dynamic_state_rules":{"additionalProperties":{"type":"string"},"title":"Dynamic State Rules","type":"object"},"identity_core":{"$ref":"#/components/schemas/IdentityCoreModel"},"idiolect":{"$ref":"#/components/schemas/IdiolectModel"},"interim_lines":{"additionalProperties":{"items":{"type":"string"},"type":"array"},"title":"Interim Lines","type":"object"},"milestone_conditions":{"additionalProperties":{"type":"string"},"title":"Milestone Conditions","type":"object"},"name":{"default":"AI Assistant","title":"Name","type":"string"},"persona_layers":{"items":{"$ref":"#/components/schemas/PersonaLayerModel"},"title":"Persona Layers","type":"array"},"quiet_hours":{"items":{"$ref":"#/components/schemas/QuietHourModel"},"title":"Quiet Hours","type":"array"},"registers":{"additionalProperties":{"$ref":"#/components/schemas/RegisterModel"},"title":"Registers","type":"object"},"signature_triggers":{"items":{"$ref":"#/components/schemas/SignatureTriggerModel"},"title":"Signature Triggers","type":"array"}},"required":["name","avatar","description","appearance_prompt","identity_core","idiolect","registers","quiet_hours","signature_triggers","persona_layers","dynamic_state_rules","milestone_conditions","interim_lines","bootstrap"],"title":"PersonalityConfigModel","type":"object"};
const schema54 = {"properties":{"max_rounds":{"default":3,"title":"Max Rounds","type":"integer"},"opening_examples":{"items":{"type":"string"},"title":"Opening Examples","type":"array"},"opening_line":{"default":"","title":"Opening Line","type":"string"},"style_instruction":{"default":"","title":"Style Instruction","type":"string"}},"required":["style_instruction","opening_line","max_rounds","opening_examples"],"title":"BootstrapConfigModel","type":"object"};

function validate119(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate119.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((data.style_instruction === undefined) && (missing0 = "style_instruction")) || ((data.opening_line === undefined) && (missing0 = "opening_line"))) || ((data.max_rounds === undefined) && (missing0 = "max_rounds"))) || ((data.opening_examples === undefined) && (missing0 = "opening_examples"))){
validate119.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.max_rounds !== undefined){
let data0 = data.max_rounds;
const _errs1 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate119.errors = [{instancePath:instancePath+"/max_rounds",schemaPath:"#/properties/max_rounds/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.opening_examples !== undefined){
let data1 = data.opening_examples;
const _errs3 = errors;
if(errors === _errs3){
if(Array.isArray(data1)){
var valid1 = true;
const len0 = data1.length;
for(let i0=0; i0<len0; i0++){
const _errs5 = errors;
if(typeof data1[i0] !== "string"){
validate119.errors = [{instancePath:instancePath+"/opening_examples/" + i0,schemaPath:"#/properties/opening_examples/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid1 = _errs5 === errors;
if(!valid1){
break;
}
}
}
else {
validate119.errors = [{instancePath:instancePath+"/opening_examples",schemaPath:"#/properties/opening_examples/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.opening_line !== undefined){
const _errs7 = errors;
if(typeof data.opening_line !== "string"){
validate119.errors = [{instancePath:instancePath+"/opening_line",schemaPath:"#/properties/opening_line/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.style_instruction !== undefined){
const _errs9 = errors;
if(typeof data.style_instruction !== "string"){
validate119.errors = [{instancePath:instancePath+"/style_instruction",schemaPath:"#/properties/style_instruction/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
else {
validate119.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate119.errors = vErrors;
return errors === 0;
}
validate119.evaluated = {"props":{"max_rounds":true,"opening_examples":true,"opening_line":true,"style_instruction":true},"dynamicProps":false,"dynamicItems":false};

const schema55 = {"properties":{"attention_biases":{"items":{"type":"string"},"title":"Attention Biases","type":"array"},"identity_statement":{"default":"","title":"Identity Statement","type":"string"},"values_loved":{"items":{"type":"string"},"title":"Values Loved","type":"array"},"values_rejected":{"items":{"type":"string"},"title":"Values Rejected","type":"array"}},"required":["identity_statement","values_loved","values_rejected","attention_biases"],"title":"IdentityCoreModel","type":"object"};

function validate121(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate121.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((data.identity_statement === undefined) && (missing0 = "identity_statement")) || ((data.values_loved === undefined) && (missing0 = "values_loved"))) || ((data.values_rejected === undefined) && (missing0 = "values_rejected"))) || ((data.attention_biases === undefined) && (missing0 = "attention_biases"))){
validate121.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.attention_biases !== undefined){
let data0 = data.attention_biases;
const _errs1 = errors;
if(errors === _errs1){
if(Array.isArray(data0)){
var valid1 = true;
const len0 = data0.length;
for(let i0=0; i0<len0; i0++){
const _errs3 = errors;
if(typeof data0[i0] !== "string"){
validate121.errors = [{instancePath:instancePath+"/attention_biases/" + i0,schemaPath:"#/properties/attention_biases/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid1 = _errs3 === errors;
if(!valid1){
break;
}
}
}
else {
validate121.errors = [{instancePath:instancePath+"/attention_biases",schemaPath:"#/properties/attention_biases/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.identity_statement !== undefined){
const _errs5 = errors;
if(typeof data.identity_statement !== "string"){
validate121.errors = [{instancePath:instancePath+"/identity_statement",schemaPath:"#/properties/identity_statement/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.values_loved !== undefined){
let data3 = data.values_loved;
const _errs7 = errors;
if(errors === _errs7){
if(Array.isArray(data3)){
var valid2 = true;
const len1 = data3.length;
for(let i1=0; i1<len1; i1++){
const _errs9 = errors;
if(typeof data3[i1] !== "string"){
validate121.errors = [{instancePath:instancePath+"/values_loved/" + i1,schemaPath:"#/properties/values_loved/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid2 = _errs9 === errors;
if(!valid2){
break;
}
}
}
else {
validate121.errors = [{instancePath:instancePath+"/values_loved",schemaPath:"#/properties/values_loved/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.values_rejected !== undefined){
let data5 = data.values_rejected;
const _errs11 = errors;
if(errors === _errs11){
if(Array.isArray(data5)){
var valid3 = true;
const len2 = data5.length;
for(let i2=0; i2<len2; i2++){
const _errs13 = errors;
if(typeof data5[i2] !== "string"){
validate121.errors = [{instancePath:instancePath+"/values_rejected/" + i2,schemaPath:"#/properties/values_rejected/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid3 = _errs13 === errors;
if(!valid3){
break;
}
}
}
else {
validate121.errors = [{instancePath:instancePath+"/values_rejected",schemaPath:"#/properties/values_rejected/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
else {
validate121.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate121.errors = vErrors;
return errors === 0;
}
validate121.evaluated = {"props":{"attention_biases":true,"identity_statement":true,"values_loved":true,"values_rejected":true},"dynamicProps":false,"dynamicItems":false};

const schema56 = {"properties":{"chattiness":{"default":0.5,"maximum":1,"minimum":0,"title":"Chattiness","type":"number"},"sentence_style":{"default":"","title":"Sentence Style","type":"string"},"structural_quirks":{"items":{"type":"string"},"title":"Structural Quirks","type":"array"},"vocab_available":{"items":{"type":"string"},"title":"Vocab Available","type":"array"},"vocab_avoided":{"items":{"type":"string"},"title":"Vocab Avoided","type":"array"}},"required":["sentence_style","vocab_available","vocab_avoided","structural_quirks","chattiness"],"title":"IdiolectModel","type":"object"};

function validate123(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate123.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((data.sentence_style === undefined) && (missing0 = "sentence_style")) || ((data.vocab_available === undefined) && (missing0 = "vocab_available"))) || ((data.vocab_avoided === undefined) && (missing0 = "vocab_avoided"))) || ((data.structural_quirks === undefined) && (missing0 = "structural_quirks"))) || ((data.chattiness === undefined) && (missing0 = "chattiness"))){
validate123.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.chattiness !== undefined){
let data0 = data.chattiness;
const _errs1 = errors;
if(errors === _errs1){
if(typeof data0 == "number"){
if(data0 > 1 || isNaN(data0)){
validate123.errors = [{instancePath:instancePath+"/chattiness",schemaPath:"#/properties/chattiness/maximum",keyword:"maximum",params:{comparison: "<=", limit: 1},message:"must be <= 1"}];
return false;
}
else {
if(data0 < 0 || isNaN(data0)){
validate123.errors = [{instancePath:instancePath+"/chattiness",schemaPath:"#/properties/chattiness/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
}
else {
validate123.errors = [{instancePath:instancePath+"/chattiness",schemaPath:"#/properties/chattiness/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.sentence_style !== undefined){
const _errs3 = errors;
if(typeof data.sentence_style !== "string"){
validate123.errors = [{instancePath:instancePath+"/sentence_style",schemaPath:"#/properties/sentence_style/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.structural_quirks !== undefined){
let data2 = data.structural_quirks;
const _errs5 = errors;
if(errors === _errs5){
if(Array.isArray(data2)){
var valid1 = true;
const len0 = data2.length;
for(let i0=0; i0<len0; i0++){
const _errs7 = errors;
if(typeof data2[i0] !== "string"){
validate123.errors = [{instancePath:instancePath+"/structural_quirks/" + i0,schemaPath:"#/properties/structural_quirks/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid1 = _errs7 === errors;
if(!valid1){
break;
}
}
}
else {
validate123.errors = [{instancePath:instancePath+"/structural_quirks",schemaPath:"#/properties/structural_quirks/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.vocab_available !== undefined){
let data4 = data.vocab_available;
const _errs9 = errors;
if(errors === _errs9){
if(Array.isArray(data4)){
var valid2 = true;
const len1 = data4.length;
for(let i1=0; i1<len1; i1++){
const _errs11 = errors;
if(typeof data4[i1] !== "string"){
validate123.errors = [{instancePath:instancePath+"/vocab_available/" + i1,schemaPath:"#/properties/vocab_available/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid2 = _errs11 === errors;
if(!valid2){
break;
}
}
}
else {
validate123.errors = [{instancePath:instancePath+"/vocab_available",schemaPath:"#/properties/vocab_available/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.vocab_avoided !== undefined){
let data6 = data.vocab_avoided;
const _errs13 = errors;
if(errors === _errs13){
if(Array.isArray(data6)){
var valid3 = true;
const len2 = data6.length;
for(let i2=0; i2<len2; i2++){
const _errs15 = errors;
if(typeof data6[i2] !== "string"){
validate123.errors = [{instancePath:instancePath+"/vocab_avoided/" + i2,schemaPath:"#/properties/vocab_avoided/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid3 = _errs15 === errors;
if(!valid3){
break;
}
}
}
else {
validate123.errors = [{instancePath:instancePath+"/vocab_avoided",schemaPath:"#/properties/vocab_avoided/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
else {
validate123.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate123.errors = vErrors;
return errors === 0;
}
validate123.evaluated = {"props":{"chattiness":true,"sentence_style":true,"structural_quirks":true,"vocab_available":true,"vocab_avoided":true},"dynamicProps":false,"dynamicItems":false};

const schema57 = {"properties":{"layer_id":{"default":"","title":"Layer Id","type":"string"},"modifiers":{"$ref":"#/components/schemas/LayerModifiersModel"},"unlock_condition":{"anyOf":[{"additionalProperties":true,"type":"object"},{"type":"null"}],"default":null,"title":"Unlock Condition"}},"required":["layer_id","unlock_condition","modifiers"],"title":"PersonaLayerModel","type":"object"};
const schema58 = {"additionalProperties":true,"type":"object"};

function validate126(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate126.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
}
else {
validate126.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate126.errors = vErrors;
return errors === 0;
}
validate126.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


function validate125(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate125.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((data.layer_id === undefined) && (missing0 = "layer_id")) || ((data.unlock_condition === undefined) && (missing0 = "unlock_condition"))) || ((data.modifiers === undefined) && (missing0 = "modifiers"))){
validate125.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.layer_id !== undefined){
const _errs1 = errors;
if(typeof data.layer_id !== "string"){
validate125.errors = [{instancePath:instancePath+"/layer_id",schemaPath:"#/properties/layer_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.modifiers !== undefined){
const _errs3 = errors;
if(!(validate126(data.modifiers, {instancePath:instancePath+"/modifiers",parentData:data,parentDataProperty:"modifiers",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate126.errors : vErrors.concat(validate126.errors);
errors = vErrors.length;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.unlock_condition !== undefined){
let data2 = data.unlock_condition;
const _errs4 = errors;
const _errs5 = errors;
let valid1 = false;
const _errs6 = errors;
if(errors === _errs6){
if(data2 && typeof data2 == "object" && !Array.isArray(data2)){
}
else {
const err0 = {instancePath:instancePath+"/unlock_condition",schemaPath:"#/properties/unlock_condition/anyOf/0/type",keyword:"type",params:{type: "object"},message:"must be object"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
}
var _valid0 = _errs6 === errors;
valid1 = valid1 || _valid0;
const _errs9 = errors;
if(data2 !== null){
const err1 = {instancePath:instancePath+"/unlock_condition",schemaPath:"#/properties/unlock_condition/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs9 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/unlock_condition",schemaPath:"#/properties/unlock_condition/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate125.errors = vErrors;
return false;
}
else {
errors = _errs5;
if(vErrors !== null){
if(_errs5){
vErrors.length = _errs5;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
else {
validate125.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate125.errors = vErrors;
return errors === 0;
}
validate125.evaluated = {"props":{"layer_id":true,"modifiers":true,"unlock_condition":true},"dynamicProps":false,"dynamicItems":false};

const schema59 = {"properties":{"clamps":{"additionalProperties":true,"title":"Clamps","type":"object"},"condition":{"default":"","title":"Condition","type":"string"}},"required":["condition","clamps"],"title":"QuietHourModel","type":"object"};

function validate129(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate129.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((data.condition === undefined) && (missing0 = "condition")) || ((data.clamps === undefined) && (missing0 = "clamps"))){
validate129.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.clamps !== undefined){
let data0 = data.clamps;
const _errs1 = errors;
if(errors === _errs1){
if(data0 && typeof data0 == "object" && !Array.isArray(data0)){
}
else {
validate129.errors = [{instancePath:instancePath+"/clamps",schemaPath:"#/properties/clamps/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.condition !== undefined){
const _errs4 = errors;
if(typeof data.condition !== "string"){
validate129.errors = [{instancePath:instancePath+"/condition",schemaPath:"#/properties/condition/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
}
}
}
else {
validate129.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate129.errors = vErrors;
return errors === 0;
}
validate129.evaluated = {"props":{"clamps":true,"condition":true},"dynamicProps":false,"dynamicItems":false};

const schema60 = {"properties":{"behavior":{"default":"","title":"Behavior","type":"string"},"description":{"default":"","title":"Description","type":"string"},"examples":{"items":{"type":"string"},"title":"Examples","type":"array"}},"required":["description","behavior","examples"],"title":"RegisterModel","type":"object"};

function validate131(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate131.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((data.description === undefined) && (missing0 = "description")) || ((data.behavior === undefined) && (missing0 = "behavior"))) || ((data.examples === undefined) && (missing0 = "examples"))){
validate131.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.behavior !== undefined){
const _errs1 = errors;
if(typeof data.behavior !== "string"){
validate131.errors = [{instancePath:instancePath+"/behavior",schemaPath:"#/properties/behavior/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description !== undefined){
const _errs3 = errors;
if(typeof data.description !== "string"){
validate131.errors = [{instancePath:instancePath+"/description",schemaPath:"#/properties/description/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.examples !== undefined){
let data2 = data.examples;
const _errs5 = errors;
if(errors === _errs5){
if(Array.isArray(data2)){
var valid1 = true;
const len0 = data2.length;
for(let i0=0; i0<len0; i0++){
const _errs7 = errors;
if(typeof data2[i0] !== "string"){
validate131.errors = [{instancePath:instancePath+"/examples/" + i0,schemaPath:"#/properties/examples/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid1 = _errs7 === errors;
if(!valid1){
break;
}
}
}
else {
validate131.errors = [{instancePath:instancePath+"/examples",schemaPath:"#/properties/examples/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
else {
validate131.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate131.errors = vErrors;
return errors === 0;
}
validate131.evaluated = {"props":{"behavior":true,"description":true,"examples":true},"dynamicProps":false,"dynamicItems":false};

const schema61 = {"properties":{"activates_when":{"default":"","title":"Activates When","type":"string"},"behavior_shift":{"default":"","title":"Behavior Shift","type":"string"},"exit_behavior":{"default":"","title":"Exit Behavior","type":"string"},"intensity_levels":{"additionalProperties":{"type":"string"},"title":"Intensity Levels","type":"object"},"trigger_id":{"default":"","title":"Trigger Id","type":"string"}},"required":["trigger_id","activates_when","behavior_shift","intensity_levels","exit_behavior"],"title":"SignatureTriggerModel","type":"object"};

function validate133(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate133.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((data.trigger_id === undefined) && (missing0 = "trigger_id")) || ((data.activates_when === undefined) && (missing0 = "activates_when"))) || ((data.behavior_shift === undefined) && (missing0 = "behavior_shift"))) || ((data.intensity_levels === undefined) && (missing0 = "intensity_levels"))) || ((data.exit_behavior === undefined) && (missing0 = "exit_behavior"))){
validate133.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.activates_when !== undefined){
const _errs1 = errors;
if(typeof data.activates_when !== "string"){
validate133.errors = [{instancePath:instancePath+"/activates_when",schemaPath:"#/properties/activates_when/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.behavior_shift !== undefined){
const _errs3 = errors;
if(typeof data.behavior_shift !== "string"){
validate133.errors = [{instancePath:instancePath+"/behavior_shift",schemaPath:"#/properties/behavior_shift/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.exit_behavior !== undefined){
const _errs5 = errors;
if(typeof data.exit_behavior !== "string"){
validate133.errors = [{instancePath:instancePath+"/exit_behavior",schemaPath:"#/properties/exit_behavior/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.intensity_levels !== undefined){
let data3 = data.intensity_levels;
const _errs7 = errors;
if(errors === _errs7){
if(data3 && typeof data3 == "object" && !Array.isArray(data3)){
for(const key0 in data3){
const _errs10 = errors;
if(typeof data3[key0] !== "string"){
validate133.errors = [{instancePath:instancePath+"/intensity_levels/" + key0.replace(/~/g, "~0").replace(/\//g, "~1"),schemaPath:"#/properties/intensity_levels/additionalProperties/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid1 = _errs10 === errors;
if(!valid1){
break;
}
}
}
else {
validate133.errors = [{instancePath:instancePath+"/intensity_levels",schemaPath:"#/properties/intensity_levels/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.trigger_id !== undefined){
const _errs12 = errors;
if(typeof data.trigger_id !== "string"){
validate133.errors = [{instancePath:instancePath+"/trigger_id",schemaPath:"#/properties/trigger_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
else {
validate133.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate133.errors = vErrors;
return errors === 0;
}
validate133.evaluated = {"props":{"activates_when":true,"behavior_shift":true,"exit_behavior":true,"intensity_levels":true,"trigger_id":true},"dynamicProps":false,"dynamicItems":false};


function validate118(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate118.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((((((((((data.name === undefined) && (missing0 = "name")) || ((data.avatar === undefined) && (missing0 = "avatar"))) || ((data.description === undefined) && (missing0 = "description"))) || ((data.appearance_prompt === undefined) && (missing0 = "appearance_prompt"))) || ((data.identity_core === undefined) && (missing0 = "identity_core"))) || ((data.idiolect === undefined) && (missing0 = "idiolect"))) || ((data.registers === undefined) && (missing0 = "registers"))) || ((data.quiet_hours === undefined) && (missing0 = "quiet_hours"))) || ((data.signature_triggers === undefined) && (missing0 = "signature_triggers"))) || ((data.persona_layers === undefined) && (missing0 = "persona_layers"))) || ((data.dynamic_state_rules === undefined) && (missing0 = "dynamic_state_rules"))) || ((data.milestone_conditions === undefined) && (missing0 = "milestone_conditions"))) || ((data.interim_lines === undefined) && (missing0 = "interim_lines"))) || ((data.bootstrap === undefined) && (missing0 = "bootstrap"))){
validate118.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.appearance_prompt !== undefined){
const _errs1 = errors;
if(typeof data.appearance_prompt !== "string"){
validate118.errors = [{instancePath:instancePath+"/appearance_prompt",schemaPath:"#/properties/appearance_prompt/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.avatar !== undefined){
const _errs3 = errors;
if(typeof data.avatar !== "string"){
validate118.errors = [{instancePath:instancePath+"/avatar",schemaPath:"#/properties/avatar/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.bootstrap !== undefined){
let data2 = data.bootstrap;
const _errs5 = errors;
const _errs6 = errors;
let valid1 = false;
const _errs7 = errors;
if(!(validate119(data2, {instancePath:instancePath+"/bootstrap",parentData:data,parentDataProperty:"bootstrap",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate119.errors : vErrors.concat(validate119.errors);
errors = vErrors.length;
}
var _valid0 = _errs7 === errors;
valid1 = valid1 || _valid0;
if(_valid0){
var props0 = {};
props0.max_rounds = true;
props0.opening_examples = true;
props0.opening_line = true;
props0.style_instruction = true;
}
const _errs8 = errors;
if(data2 !== null){
const err0 = {instancePath:instancePath+"/bootstrap",schemaPath:"#/properties/bootstrap/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs8 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err1 = {instancePath:instancePath+"/bootstrap",schemaPath:"#/properties/bootstrap/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
validate118.errors = vErrors;
return false;
}
else {
errors = _errs6;
if(vErrors !== null){
if(_errs6){
vErrors.length = _errs6;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description !== undefined){
const _errs10 = errors;
if(typeof data.description !== "string"){
validate118.errors = [{instancePath:instancePath+"/description",schemaPath:"#/properties/description/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs10 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.dynamic_state_rules !== undefined){
let data4 = data.dynamic_state_rules;
const _errs12 = errors;
if(errors === _errs12){
if(data4 && typeof data4 == "object" && !Array.isArray(data4)){
for(const key0 in data4){
const _errs15 = errors;
if(typeof data4[key0] !== "string"){
validate118.errors = [{instancePath:instancePath+"/dynamic_state_rules/" + key0.replace(/~/g, "~0").replace(/\//g, "~1"),schemaPath:"#/properties/dynamic_state_rules/additionalProperties/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid2 = _errs15 === errors;
if(!valid2){
break;
}
}
}
else {
validate118.errors = [{instancePath:instancePath+"/dynamic_state_rules",schemaPath:"#/properties/dynamic_state_rules/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.identity_core !== undefined){
const _errs17 = errors;
if(!(validate121(data.identity_core, {instancePath:instancePath+"/identity_core",parentData:data,parentDataProperty:"identity_core",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate121.errors : vErrors.concat(validate121.errors);
errors = vErrors.length;
}
var valid0 = _errs17 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.idiolect !== undefined){
const _errs18 = errors;
if(!(validate123(data.idiolect, {instancePath:instancePath+"/idiolect",parentData:data,parentDataProperty:"idiolect",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate123.errors : vErrors.concat(validate123.errors);
errors = vErrors.length;
}
var valid0 = _errs18 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.interim_lines !== undefined){
let data8 = data.interim_lines;
const _errs19 = errors;
if(errors === _errs19){
if(data8 && typeof data8 == "object" && !Array.isArray(data8)){
for(const key1 in data8){
let data9 = data8[key1];
const _errs22 = errors;
if(errors === _errs22){
if(Array.isArray(data9)){
var valid4 = true;
const len0 = data9.length;
for(let i0=0; i0<len0; i0++){
const _errs24 = errors;
if(typeof data9[i0] !== "string"){
validate118.errors = [{instancePath:instancePath+"/interim_lines/" + key1.replace(/~/g, "~0").replace(/\//g, "~1")+"/" + i0,schemaPath:"#/properties/interim_lines/additionalProperties/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid4 = _errs24 === errors;
if(!valid4){
break;
}
}
}
else {
validate118.errors = [{instancePath:instancePath+"/interim_lines/" + key1.replace(/~/g, "~0").replace(/\//g, "~1"),schemaPath:"#/properties/interim_lines/additionalProperties/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid3 = _errs22 === errors;
if(!valid3){
break;
}
}
}
else {
validate118.errors = [{instancePath:instancePath+"/interim_lines",schemaPath:"#/properties/interim_lines/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs19 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.milestone_conditions !== undefined){
let data11 = data.milestone_conditions;
const _errs26 = errors;
if(errors === _errs26){
if(data11 && typeof data11 == "object" && !Array.isArray(data11)){
for(const key2 in data11){
const _errs29 = errors;
if(typeof data11[key2] !== "string"){
validate118.errors = [{instancePath:instancePath+"/milestone_conditions/" + key2.replace(/~/g, "~0").replace(/\//g, "~1"),schemaPath:"#/properties/milestone_conditions/additionalProperties/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid5 = _errs29 === errors;
if(!valid5){
break;
}
}
}
else {
validate118.errors = [{instancePath:instancePath+"/milestone_conditions",schemaPath:"#/properties/milestone_conditions/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs26 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.name !== undefined){
const _errs31 = errors;
if(typeof data.name !== "string"){
validate118.errors = [{instancePath:instancePath+"/name",schemaPath:"#/properties/name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs31 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.persona_layers !== undefined){
let data14 = data.persona_layers;
const _errs33 = errors;
if(errors === _errs33){
if(Array.isArray(data14)){
var valid6 = true;
const len1 = data14.length;
for(let i1=0; i1<len1; i1++){
const _errs35 = errors;
if(!(validate125(data14[i1], {instancePath:instancePath+"/persona_layers/" + i1,parentData:data14,parentDataProperty:i1,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate125.errors : vErrors.concat(validate125.errors);
errors = vErrors.length;
}
var valid6 = _errs35 === errors;
if(!valid6){
break;
}
}
}
else {
validate118.errors = [{instancePath:instancePath+"/persona_layers",schemaPath:"#/properties/persona_layers/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs33 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.quiet_hours !== undefined){
let data16 = data.quiet_hours;
const _errs36 = errors;
if(errors === _errs36){
if(Array.isArray(data16)){
var valid7 = true;
const len2 = data16.length;
for(let i2=0; i2<len2; i2++){
const _errs38 = errors;
if(!(validate129(data16[i2], {instancePath:instancePath+"/quiet_hours/" + i2,parentData:data16,parentDataProperty:i2,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate129.errors : vErrors.concat(validate129.errors);
errors = vErrors.length;
}
var valid7 = _errs38 === errors;
if(!valid7){
break;
}
}
}
else {
validate118.errors = [{instancePath:instancePath+"/quiet_hours",schemaPath:"#/properties/quiet_hours/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs36 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.registers !== undefined){
let data18 = data.registers;
const _errs39 = errors;
if(errors === _errs39){
if(data18 && typeof data18 == "object" && !Array.isArray(data18)){
for(const key3 in data18){
const _errs42 = errors;
if(!(validate131(data18[key3], {instancePath:instancePath+"/registers/" + key3.replace(/~/g, "~0").replace(/\//g, "~1"),parentData:data18,parentDataProperty:key3,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate131.errors : vErrors.concat(validate131.errors);
errors = vErrors.length;
}
var valid8 = _errs42 === errors;
if(!valid8){
break;
}
}
}
else {
validate118.errors = [{instancePath:instancePath+"/registers",schemaPath:"#/properties/registers/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs39 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.signature_triggers !== undefined){
let data20 = data.signature_triggers;
const _errs43 = errors;
if(errors === _errs43){
if(Array.isArray(data20)){
var valid9 = true;
const len3 = data20.length;
for(let i3=0; i3<len3; i3++){
const _errs45 = errors;
if(!(validate133(data20[i3], {instancePath:instancePath+"/signature_triggers/" + i3,parentData:data20,parentDataProperty:i3,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate133.errors : vErrors.concat(validate133.errors);
errors = vErrors.length;
}
var valid9 = _errs45 === errors;
if(!valid9){
break;
}
}
}
else {
validate118.errors = [{instancePath:instancePath+"/signature_triggers",schemaPath:"#/properties/signature_triggers/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs43 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
else {
validate118.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate118.errors = vErrors;
return errors === 0;
}
validate118.evaluated = {"props":{"appearance_prompt":true,"avatar":true,"bootstrap":true,"description":true,"dynamic_state_rules":true,"identity_core":true,"idiolect":true,"interim_lines":true,"milestone_conditions":true,"name":true,"persona_layers":true,"quiet_hours":true,"registers":true,"signature_triggers":true},"dynamicProps":false,"dynamicItems":false};

const schema62 = {"properties":{"deep_persona_enabled":{"default":true,"title":"Deep Persona Enabled","type":"boolean"},"state_memory_enabled":{"default":true,"title":"State Memory Enabled","type":"boolean"},"state_transition_enabled":{"default":true,"title":"State Transition Enabled","type":"boolean"}},"required":["state_memory_enabled","state_transition_enabled","deep_persona_enabled"],"title":"PersonalitySettingsModel","type":"object"};

function validate136(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate136.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((data.state_memory_enabled === undefined) && (missing0 = "state_memory_enabled")) || ((data.state_transition_enabled === undefined) && (missing0 = "state_transition_enabled"))) || ((data.deep_persona_enabled === undefined) && (missing0 = "deep_persona_enabled"))){
validate136.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.deep_persona_enabled !== undefined){
const _errs1 = errors;
if(typeof data.deep_persona_enabled !== "boolean"){
validate136.errors = [{instancePath:instancePath+"/deep_persona_enabled",schemaPath:"#/properties/deep_persona_enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.state_memory_enabled !== undefined){
const _errs3 = errors;
if(typeof data.state_memory_enabled !== "boolean"){
validate136.errors = [{instancePath:instancePath+"/state_memory_enabled",schemaPath:"#/properties/state_memory_enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.state_transition_enabled !== undefined){
const _errs5 = errors;
if(typeof data.state_transition_enabled !== "boolean"){
validate136.errors = [{instancePath:instancePath+"/state_transition_enabled",schemaPath:"#/properties/state_transition_enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
else {
validate136.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate136.errors = vErrors;
return errors === 0;
}
validate136.evaluated = {"props":{"deep_persona_enabled":true,"state_memory_enabled":true,"state_transition_enabled":true},"dynamicProps":false,"dynamicItems":false};

const schema63 = {"properties":{"allow_ask_in_background":{"default":false,"title":"Allow Ask In Background","type":"boolean"},"allow_interjection":{"default":false,"title":"Allow Interjection","type":"boolean"},"allow_media_grounding_for_conversation":{"default":true,"title":"Allow Media Grounding For Conversation","type":"boolean"},"conversation_rhythm_enabled":{"default":true,"title":"Conversation Rhythm Enabled","type":"boolean"},"conversation_rhythm_mode":{"default":"natural","title":"Conversation Rhythm Mode","type":"string"},"default_chat_workspace_path":{"anyOf":[{"type":"string"},{"type":"null"}],"title":"Default Chat Workspace Path"},"first_conversation_completed":{"default":false,"description":"Legacy onboarding state retained for existing saved preferences. The chat UI no longer uses it to show starter prompts.","title":"First Conversation Completed","type":"boolean"},"language":{"default":"zh","title":"Language","type":"string"},"onboarding_completed":{"default":false,"title":"Onboarding Completed","type":"boolean"},"product_tour_completed":{"default":false,"description":"True once the user has completed (or skipped) the one-time main-page product tour shown on first visit after onboarding.","title":"Product Tour Completed","type":"boolean"},"scenario":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Scenario"},"streaming_chat_enabled":{"default":false,"title":"Streaming Chat Enabled","type":"boolean"},"suggestion_dismissals":{"additionalProperties":{"$ref":"#/components/schemas/DismissalRecord"},"description":"Map of dedupe_key → DismissalRecord. The signal matcher filters out any candidate whose dedupe_key appears here and whose TTL (based on kind) has not yet expired.","title":"Suggestion Dismissals","type":"object"},"user_mode":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"User Mode"}},"required":["onboarding_completed","first_conversation_completed","product_tour_completed","suggestion_dismissals","user_mode","scenario","language","default_chat_workspace_path","streaming_chat_enabled","conversation_rhythm_enabled","conversation_rhythm_mode","allow_media_grounding_for_conversation","allow_interjection","allow_ask_in_background"],"title":"UserPreferencesModel","type":"object"};
const schema64 = {"properties":{"dedupe_key":{"title":"Dedupe Key","type":"string"},"dismissed_at":{"format":"date-time","title":"Dismissed At","type":"string"},"kind":{"$ref":"#/components/schemas/DismissalKind"},"title":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Title"}},"required":["dedupe_key","dismissed_at","kind","title"],"title":"DismissalRecord","type":"object"};
const schema65 = {"description":"How the user dismissed a suggestion. Determines the TTL applied.","enum":["transient","explicit","never"],"title":"DismissalKind","type":"string"};

function validate140(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate140.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(typeof data !== "string"){
validate140.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((data === "transient") || (data === "explicit")) || (data === "never"))){
validate140.errors = [{instancePath,schemaPath:"#/enum",keyword:"enum",params:{allowedValues: schema65.enum},message:"must be equal to one of the allowed values"}];
return false;
}
validate140.errors = vErrors;
return errors === 0;
}
validate140.evaluated = {"dynamicProps":false,"dynamicItems":false};


function validate139(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate139.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((data.dedupe_key === undefined) && (missing0 = "dedupe_key")) || ((data.dismissed_at === undefined) && (missing0 = "dismissed_at"))) || ((data.kind === undefined) && (missing0 = "kind"))) || ((data.title === undefined) && (missing0 = "title"))){
validate139.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.dedupe_key !== undefined){
const _errs1 = errors;
if(typeof data.dedupe_key !== "string"){
validate139.errors = [{instancePath:instancePath+"/dedupe_key",schemaPath:"#/properties/dedupe_key/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.dismissed_at !== undefined){
const _errs3 = errors;
if(errors === _errs3){
if(errors === _errs3){
if(!(typeof data.dismissed_at === "string")){
validate139.errors = [{instancePath:instancePath+"/dismissed_at",schemaPath:"#/properties/dismissed_at/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.kind !== undefined){
const _errs5 = errors;
if(!(validate140(data.kind, {instancePath:instancePath+"/kind",parentData:data,parentDataProperty:"kind",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate140.errors : vErrors.concat(validate140.errors);
errors = vErrors.length;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.title !== undefined){
let data3 = data.title;
const _errs6 = errors;
const _errs7 = errors;
let valid1 = false;
const _errs8 = errors;
if(typeof data3 !== "string"){
const err0 = {instancePath:instancePath+"/title",schemaPath:"#/properties/title/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs8 === errors;
valid1 = valid1 || _valid0;
const _errs10 = errors;
if(data3 !== null){
const err1 = {instancePath:instancePath+"/title",schemaPath:"#/properties/title/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs10 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/title",schemaPath:"#/properties/title/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate139.errors = vErrors;
return false;
}
else {
errors = _errs7;
if(vErrors !== null){
if(_errs7){
vErrors.length = _errs7;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
else {
validate139.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate139.errors = vErrors;
return errors === 0;
}
validate139.evaluated = {"props":{"dedupe_key":true,"dismissed_at":true,"kind":true,"title":true},"dynamicProps":false,"dynamicItems":false};


function validate138(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate138.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((((((((((data.onboarding_completed === undefined) && (missing0 = "onboarding_completed")) || ((data.first_conversation_completed === undefined) && (missing0 = "first_conversation_completed"))) || ((data.product_tour_completed === undefined) && (missing0 = "product_tour_completed"))) || ((data.suggestion_dismissals === undefined) && (missing0 = "suggestion_dismissals"))) || ((data.user_mode === undefined) && (missing0 = "user_mode"))) || ((data.scenario === undefined) && (missing0 = "scenario"))) || ((data.language === undefined) && (missing0 = "language"))) || ((data.default_chat_workspace_path === undefined) && (missing0 = "default_chat_workspace_path"))) || ((data.streaming_chat_enabled === undefined) && (missing0 = "streaming_chat_enabled"))) || ((data.conversation_rhythm_enabled === undefined) && (missing0 = "conversation_rhythm_enabled"))) || ((data.conversation_rhythm_mode === undefined) && (missing0 = "conversation_rhythm_mode"))) || ((data.allow_media_grounding_for_conversation === undefined) && (missing0 = "allow_media_grounding_for_conversation"))) || ((data.allow_interjection === undefined) && (missing0 = "allow_interjection"))) || ((data.allow_ask_in_background === undefined) && (missing0 = "allow_ask_in_background"))){
validate138.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.allow_ask_in_background !== undefined){
const _errs1 = errors;
if(typeof data.allow_ask_in_background !== "boolean"){
validate138.errors = [{instancePath:instancePath+"/allow_ask_in_background",schemaPath:"#/properties/allow_ask_in_background/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.allow_interjection !== undefined){
const _errs3 = errors;
if(typeof data.allow_interjection !== "boolean"){
validate138.errors = [{instancePath:instancePath+"/allow_interjection",schemaPath:"#/properties/allow_interjection/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.allow_media_grounding_for_conversation !== undefined){
const _errs5 = errors;
if(typeof data.allow_media_grounding_for_conversation !== "boolean"){
validate138.errors = [{instancePath:instancePath+"/allow_media_grounding_for_conversation",schemaPath:"#/properties/allow_media_grounding_for_conversation/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.conversation_rhythm_enabled !== undefined){
const _errs7 = errors;
if(typeof data.conversation_rhythm_enabled !== "boolean"){
validate138.errors = [{instancePath:instancePath+"/conversation_rhythm_enabled",schemaPath:"#/properties/conversation_rhythm_enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.conversation_rhythm_mode !== undefined){
const _errs9 = errors;
if(typeof data.conversation_rhythm_mode !== "string"){
validate138.errors = [{instancePath:instancePath+"/conversation_rhythm_mode",schemaPath:"#/properties/conversation_rhythm_mode/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.default_chat_workspace_path !== undefined){
let data5 = data.default_chat_workspace_path;
const _errs11 = errors;
const _errs12 = errors;
let valid1 = false;
const _errs13 = errors;
if(typeof data5 !== "string"){
const err0 = {instancePath:instancePath+"/default_chat_workspace_path",schemaPath:"#/properties/default_chat_workspace_path/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs13 === errors;
valid1 = valid1 || _valid0;
const _errs15 = errors;
if(data5 !== null){
const err1 = {instancePath:instancePath+"/default_chat_workspace_path",schemaPath:"#/properties/default_chat_workspace_path/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs15 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/default_chat_workspace_path",schemaPath:"#/properties/default_chat_workspace_path/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate138.errors = vErrors;
return false;
}
else {
errors = _errs12;
if(vErrors !== null){
if(_errs12){
vErrors.length = _errs12;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.first_conversation_completed !== undefined){
const _errs17 = errors;
if(typeof data.first_conversation_completed !== "boolean"){
validate138.errors = [{instancePath:instancePath+"/first_conversation_completed",schemaPath:"#/properties/first_conversation_completed/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs17 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.language !== undefined){
const _errs19 = errors;
if(typeof data.language !== "string"){
validate138.errors = [{instancePath:instancePath+"/language",schemaPath:"#/properties/language/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs19 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.onboarding_completed !== undefined){
const _errs21 = errors;
if(typeof data.onboarding_completed !== "boolean"){
validate138.errors = [{instancePath:instancePath+"/onboarding_completed",schemaPath:"#/properties/onboarding_completed/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs21 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.product_tour_completed !== undefined){
const _errs23 = errors;
if(typeof data.product_tour_completed !== "boolean"){
validate138.errors = [{instancePath:instancePath+"/product_tour_completed",schemaPath:"#/properties/product_tour_completed/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs23 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.scenario !== undefined){
let data10 = data.scenario;
const _errs25 = errors;
const _errs26 = errors;
let valid2 = false;
const _errs27 = errors;
if(typeof data10 !== "string"){
const err3 = {instancePath:instancePath+"/scenario",schemaPath:"#/properties/scenario/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs27 === errors;
valid2 = valid2 || _valid1;
const _errs29 = errors;
if(data10 !== null){
const err4 = {instancePath:instancePath+"/scenario",schemaPath:"#/properties/scenario/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs29 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err5 = {instancePath:instancePath+"/scenario",schemaPath:"#/properties/scenario/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate138.errors = vErrors;
return false;
}
else {
errors = _errs26;
if(vErrors !== null){
if(_errs26){
vErrors.length = _errs26;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs25 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.streaming_chat_enabled !== undefined){
const _errs31 = errors;
if(typeof data.streaming_chat_enabled !== "boolean"){
validate138.errors = [{instancePath:instancePath+"/streaming_chat_enabled",schemaPath:"#/properties/streaming_chat_enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs31 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.suggestion_dismissals !== undefined){
let data12 = data.suggestion_dismissals;
const _errs33 = errors;
if(errors === _errs33){
if(data12 && typeof data12 == "object" && !Array.isArray(data12)){
for(const key0 in data12){
const _errs36 = errors;
if(!(validate139(data12[key0], {instancePath:instancePath+"/suggestion_dismissals/" + key0.replace(/~/g, "~0").replace(/\//g, "~1"),parentData:data12,parentDataProperty:key0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate139.errors : vErrors.concat(validate139.errors);
errors = vErrors.length;
}
var valid3 = _errs36 === errors;
if(!valid3){
break;
}
}
}
else {
validate138.errors = [{instancePath:instancePath+"/suggestion_dismissals",schemaPath:"#/properties/suggestion_dismissals/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs33 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.user_mode !== undefined){
let data14 = data.user_mode;
const _errs37 = errors;
const _errs38 = errors;
let valid4 = false;
const _errs39 = errors;
if(typeof data14 !== "string"){
const err6 = {instancePath:instancePath+"/user_mode",schemaPath:"#/properties/user_mode/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid2 = _errs39 === errors;
valid4 = valid4 || _valid2;
const _errs41 = errors;
if(data14 !== null){
const err7 = {instancePath:instancePath+"/user_mode",schemaPath:"#/properties/user_mode/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
}
var _valid2 = _errs41 === errors;
valid4 = valid4 || _valid2;
if(!valid4){
const err8 = {instancePath:instancePath+"/user_mode",schemaPath:"#/properties/user_mode/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
validate138.errors = vErrors;
return false;
}
else {
errors = _errs38;
if(vErrors !== null){
if(_errs38){
vErrors.length = _errs38;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs37 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
else {
validate138.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate138.errors = vErrors;
return errors === 0;
}
validate138.evaluated = {"props":{"allow_ask_in_background":true,"allow_interjection":true,"allow_media_grounding_for_conversation":true,"conversation_rhythm_enabled":true,"conversation_rhythm_mode":true,"default_chat_workspace_path":true,"first_conversation_completed":true,"language":true,"onboarding_completed":true,"product_tour_completed":true,"scenario":true,"streaming_chat_enabled":true,"suggestion_dismissals":true,"user_mode":true},"dynamicProps":false,"dynamicItems":false};

const schema66 = {"properties":{"sources":{"$ref":"#/components/schemas/TimelineSourcesConfigModel"}},"required":["sources"],"title":"TimelineConfigModel","type":"object"};
const schema67 = {"properties":{"calendar":{"anyOf":[{"$ref":"#/components/schemas/TimelineSourceConfigModel"},{"type":"null"}],"default":null},"chrome_history":{"anyOf":[{"$ref":"#/components/schemas/TimelineSourceConfigModel"},{"type":"null"}],"default":null},"git_activity":{"anyOf":[{"$ref":"#/components/schemas/TimelineSourceConfigModel"},{"type":"null"}],"default":null},"netease_music":{"anyOf":[{"$ref":"#/components/schemas/TimelineSourceConfigModel"},{"type":"null"}],"default":null},"photo_library":{"$ref":"#/components/schemas/TimelineSourceConfigModel"},"screen_time":{"anyOf":[{"$ref":"#/components/schemas/TimelineSourceConfigModel"},{"type":"null"}],"default":null},"terminal_history":{"anyOf":[{"$ref":"#/components/schemas/TimelineSourceConfigModel"},{"type":"null"}],"default":null}},"required":["photo_library","calendar","chrome_history","git_activity","screen_time","terminal_history","netease_music"],"title":"TimelineSourcesConfigModel","type":"object"};
const schema68 = {"properties":{"default_retention_mode":{"default":"analyze_only","title":"Default Retention Mode","type":"string"},"edge_whitelist":{"items":{"type":"string"},"title":"Edge Whitelist","type":"array"},"enabled":{"default":true,"title":"Enabled","type":"boolean"},"fetch_page_content":{"default":false,"title":"Fetch Page Content","type":"boolean"},"source_path":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Source Path"},"storage_mode":{"default":"managed","title":"Storage Mode","type":"string"},"sync_interval_minutes":{"default":15,"minimum":1,"title":"Sync Interval Minutes","type":"integer"},"sync_mode":{"default":"interval","title":"Sync Mode","type":"string"}},"required":["enabled","sync_mode","sync_interval_minutes","default_retention_mode","storage_mode","source_path","fetch_page_content","edge_whitelist"],"title":"TimelineSourceConfigModel","type":"object"};

function validate146(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate146.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((((data.enabled === undefined) && (missing0 = "enabled")) || ((data.sync_mode === undefined) && (missing0 = "sync_mode"))) || ((data.sync_interval_minutes === undefined) && (missing0 = "sync_interval_minutes"))) || ((data.default_retention_mode === undefined) && (missing0 = "default_retention_mode"))) || ((data.storage_mode === undefined) && (missing0 = "storage_mode"))) || ((data.source_path === undefined) && (missing0 = "source_path"))) || ((data.fetch_page_content === undefined) && (missing0 = "fetch_page_content"))) || ((data.edge_whitelist === undefined) && (missing0 = "edge_whitelist"))){
validate146.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.default_retention_mode !== undefined){
const _errs1 = errors;
if(typeof data.default_retention_mode !== "string"){
validate146.errors = [{instancePath:instancePath+"/default_retention_mode",schemaPath:"#/properties/default_retention_mode/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.edge_whitelist !== undefined){
let data1 = data.edge_whitelist;
const _errs3 = errors;
if(errors === _errs3){
if(Array.isArray(data1)){
var valid1 = true;
const len0 = data1.length;
for(let i0=0; i0<len0; i0++){
const _errs5 = errors;
if(typeof data1[i0] !== "string"){
validate146.errors = [{instancePath:instancePath+"/edge_whitelist/" + i0,schemaPath:"#/properties/edge_whitelist/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid1 = _errs5 === errors;
if(!valid1){
break;
}
}
}
else {
validate146.errors = [{instancePath:instancePath+"/edge_whitelist",schemaPath:"#/properties/edge_whitelist/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.enabled !== undefined){
const _errs7 = errors;
if(typeof data.enabled !== "boolean"){
validate146.errors = [{instancePath:instancePath+"/enabled",schemaPath:"#/properties/enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.fetch_page_content !== undefined){
const _errs9 = errors;
if(typeof data.fetch_page_content !== "boolean"){
validate146.errors = [{instancePath:instancePath+"/fetch_page_content",schemaPath:"#/properties/fetch_page_content/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.source_path !== undefined){
let data5 = data.source_path;
const _errs11 = errors;
const _errs12 = errors;
let valid2 = false;
const _errs13 = errors;
if(typeof data5 !== "string"){
const err0 = {instancePath:instancePath+"/source_path",schemaPath:"#/properties/source_path/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs13 === errors;
valid2 = valid2 || _valid0;
const _errs15 = errors;
if(data5 !== null){
const err1 = {instancePath:instancePath+"/source_path",schemaPath:"#/properties/source_path/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs15 === errors;
valid2 = valid2 || _valid0;
if(!valid2){
const err2 = {instancePath:instancePath+"/source_path",schemaPath:"#/properties/source_path/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate146.errors = vErrors;
return false;
}
else {
errors = _errs12;
if(vErrors !== null){
if(_errs12){
vErrors.length = _errs12;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.storage_mode !== undefined){
const _errs17 = errors;
if(typeof data.storage_mode !== "string"){
validate146.errors = [{instancePath:instancePath+"/storage_mode",schemaPath:"#/properties/storage_mode/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs17 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.sync_interval_minutes !== undefined){
let data7 = data.sync_interval_minutes;
const _errs19 = errors;
if(!((typeof data7 == "number") && (!(data7 % 1) && !isNaN(data7)))){
validate146.errors = [{instancePath:instancePath+"/sync_interval_minutes",schemaPath:"#/properties/sync_interval_minutes/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs19){
if(typeof data7 == "number"){
if(data7 < 1 || isNaN(data7)){
validate146.errors = [{instancePath:instancePath+"/sync_interval_minutes",schemaPath:"#/properties/sync_interval_minutes/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"}];
return false;
}
}
}
var valid0 = _errs19 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.sync_mode !== undefined){
const _errs21 = errors;
if(typeof data.sync_mode !== "string"){
validate146.errors = [{instancePath:instancePath+"/sync_mode",schemaPath:"#/properties/sync_mode/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs21 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
}
else {
validate146.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate146.errors = vErrors;
return errors === 0;
}
validate146.evaluated = {"props":{"default_retention_mode":true,"edge_whitelist":true,"enabled":true,"fetch_page_content":true,"source_path":true,"storage_mode":true,"sync_interval_minutes":true,"sync_mode":true},"dynamicProps":false,"dynamicItems":false};


function validate145(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate145.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((((data.photo_library === undefined) && (missing0 = "photo_library")) || ((data.calendar === undefined) && (missing0 = "calendar"))) || ((data.chrome_history === undefined) && (missing0 = "chrome_history"))) || ((data.git_activity === undefined) && (missing0 = "git_activity"))) || ((data.screen_time === undefined) && (missing0 = "screen_time"))) || ((data.terminal_history === undefined) && (missing0 = "terminal_history"))) || ((data.netease_music === undefined) && (missing0 = "netease_music"))){
validate145.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.calendar !== undefined){
let data0 = data.calendar;
const _errs1 = errors;
const _errs2 = errors;
let valid1 = false;
const _errs3 = errors;
if(!(validate146(data0, {instancePath:instancePath+"/calendar",parentData:data,parentDataProperty:"calendar",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate146.errors : vErrors.concat(validate146.errors);
errors = vErrors.length;
}
var _valid0 = _errs3 === errors;
valid1 = valid1 || _valid0;
if(_valid0){
var props0 = {};
props0.default_retention_mode = true;
props0.edge_whitelist = true;
props0.enabled = true;
props0.fetch_page_content = true;
props0.source_path = true;
props0.storage_mode = true;
props0.sync_interval_minutes = true;
props0.sync_mode = true;
}
const _errs4 = errors;
if(data0 !== null){
const err0 = {instancePath:instancePath+"/calendar",schemaPath:"#/properties/calendar/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs4 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err1 = {instancePath:instancePath+"/calendar",schemaPath:"#/properties/calendar/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
validate145.errors = vErrors;
return false;
}
else {
errors = _errs2;
if(vErrors !== null){
if(_errs2){
vErrors.length = _errs2;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.chrome_history !== undefined){
let data1 = data.chrome_history;
const _errs6 = errors;
const _errs7 = errors;
let valid2 = false;
const _errs8 = errors;
if(!(validate146(data1, {instancePath:instancePath+"/chrome_history",parentData:data,parentDataProperty:"chrome_history",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate146.errors : vErrors.concat(validate146.errors);
errors = vErrors.length;
}
var _valid1 = _errs8 === errors;
valid2 = valid2 || _valid1;
if(_valid1){
var props1 = {};
props1.default_retention_mode = true;
props1.edge_whitelist = true;
props1.enabled = true;
props1.fetch_page_content = true;
props1.source_path = true;
props1.storage_mode = true;
props1.sync_interval_minutes = true;
props1.sync_mode = true;
}
const _errs9 = errors;
if(data1 !== null){
const err2 = {instancePath:instancePath+"/chrome_history",schemaPath:"#/properties/chrome_history/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
}
var _valid1 = _errs9 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err3 = {instancePath:instancePath+"/chrome_history",schemaPath:"#/properties/chrome_history/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
validate145.errors = vErrors;
return false;
}
else {
errors = _errs7;
if(vErrors !== null){
if(_errs7){
vErrors.length = _errs7;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.git_activity !== undefined){
let data2 = data.git_activity;
const _errs11 = errors;
const _errs12 = errors;
let valid3 = false;
const _errs13 = errors;
if(!(validate146(data2, {instancePath:instancePath+"/git_activity",parentData:data,parentDataProperty:"git_activity",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate146.errors : vErrors.concat(validate146.errors);
errors = vErrors.length;
}
var _valid2 = _errs13 === errors;
valid3 = valid3 || _valid2;
if(_valid2){
var props2 = {};
props2.default_retention_mode = true;
props2.edge_whitelist = true;
props2.enabled = true;
props2.fetch_page_content = true;
props2.source_path = true;
props2.storage_mode = true;
props2.sync_interval_minutes = true;
props2.sync_mode = true;
}
const _errs14 = errors;
if(data2 !== null){
const err4 = {instancePath:instancePath+"/git_activity",schemaPath:"#/properties/git_activity/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid2 = _errs14 === errors;
valid3 = valid3 || _valid2;
if(!valid3){
const err5 = {instancePath:instancePath+"/git_activity",schemaPath:"#/properties/git_activity/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate145.errors = vErrors;
return false;
}
else {
errors = _errs12;
if(vErrors !== null){
if(_errs12){
vErrors.length = _errs12;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.netease_music !== undefined){
let data3 = data.netease_music;
const _errs16 = errors;
const _errs17 = errors;
let valid4 = false;
const _errs18 = errors;
if(!(validate146(data3, {instancePath:instancePath+"/netease_music",parentData:data,parentDataProperty:"netease_music",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate146.errors : vErrors.concat(validate146.errors);
errors = vErrors.length;
}
var _valid3 = _errs18 === errors;
valid4 = valid4 || _valid3;
if(_valid3){
var props3 = {};
props3.default_retention_mode = true;
props3.edge_whitelist = true;
props3.enabled = true;
props3.fetch_page_content = true;
props3.source_path = true;
props3.storage_mode = true;
props3.sync_interval_minutes = true;
props3.sync_mode = true;
}
const _errs19 = errors;
if(data3 !== null){
const err6 = {instancePath:instancePath+"/netease_music",schemaPath:"#/properties/netease_music/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid3 = _errs19 === errors;
valid4 = valid4 || _valid3;
if(!valid4){
const err7 = {instancePath:instancePath+"/netease_music",schemaPath:"#/properties/netease_music/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
validate145.errors = vErrors;
return false;
}
else {
errors = _errs17;
if(vErrors !== null){
if(_errs17){
vErrors.length = _errs17;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs16 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.photo_library !== undefined){
const _errs21 = errors;
if(!(validate146(data.photo_library, {instancePath:instancePath+"/photo_library",parentData:data,parentDataProperty:"photo_library",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate146.errors : vErrors.concat(validate146.errors);
errors = vErrors.length;
}
var valid0 = _errs21 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.screen_time !== undefined){
let data5 = data.screen_time;
const _errs22 = errors;
const _errs23 = errors;
let valid5 = false;
const _errs24 = errors;
if(!(validate146(data5, {instancePath:instancePath+"/screen_time",parentData:data,parentDataProperty:"screen_time",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate146.errors : vErrors.concat(validate146.errors);
errors = vErrors.length;
}
var _valid4 = _errs24 === errors;
valid5 = valid5 || _valid4;
if(_valid4){
var props4 = {};
props4.default_retention_mode = true;
props4.edge_whitelist = true;
props4.enabled = true;
props4.fetch_page_content = true;
props4.source_path = true;
props4.storage_mode = true;
props4.sync_interval_minutes = true;
props4.sync_mode = true;
}
const _errs25 = errors;
if(data5 !== null){
const err8 = {instancePath:instancePath+"/screen_time",schemaPath:"#/properties/screen_time/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
}
var _valid4 = _errs25 === errors;
valid5 = valid5 || _valid4;
if(!valid5){
const err9 = {instancePath:instancePath+"/screen_time",schemaPath:"#/properties/screen_time/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err9];
}
else {
vErrors.push(err9);
}
errors++;
validate145.errors = vErrors;
return false;
}
else {
errors = _errs23;
if(vErrors !== null){
if(_errs23){
vErrors.length = _errs23;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs22 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.terminal_history !== undefined){
let data6 = data.terminal_history;
const _errs27 = errors;
const _errs28 = errors;
let valid6 = false;
const _errs29 = errors;
if(!(validate146(data6, {instancePath:instancePath+"/terminal_history",parentData:data,parentDataProperty:"terminal_history",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate146.errors : vErrors.concat(validate146.errors);
errors = vErrors.length;
}
var _valid5 = _errs29 === errors;
valid6 = valid6 || _valid5;
if(_valid5){
var props5 = {};
props5.default_retention_mode = true;
props5.edge_whitelist = true;
props5.enabled = true;
props5.fetch_page_content = true;
props5.source_path = true;
props5.storage_mode = true;
props5.sync_interval_minutes = true;
props5.sync_mode = true;
}
const _errs30 = errors;
if(data6 !== null){
const err10 = {instancePath:instancePath+"/terminal_history",schemaPath:"#/properties/terminal_history/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
}
var _valid5 = _errs30 === errors;
valid6 = valid6 || _valid5;
if(!valid6){
const err11 = {instancePath:instancePath+"/terminal_history",schemaPath:"#/properties/terminal_history/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err11];
}
else {
vErrors.push(err11);
}
errors++;
validate145.errors = vErrors;
return false;
}
else {
errors = _errs28;
if(vErrors !== null){
if(_errs28){
vErrors.length = _errs28;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs27 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
else {
validate145.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate145.errors = vErrors;
return errors === 0;
}
validate145.evaluated = {"props":{"calendar":true,"chrome_history":true,"git_activity":true,"netease_music":true,"photo_library":true,"screen_time":true,"terminal_history":true},"dynamicProps":false,"dynamicItems":false};


function validate144(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate144.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((data.sources === undefined) && (missing0 = "sources")){
validate144.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.sources !== undefined){
if(!(validate145(data.sources, {instancePath:instancePath+"/sources",parentData:data,parentDataProperty:"sources",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate145.errors : vErrors.concat(validate145.errors);
errors = vErrors.length;
}
}
}
}
else {
validate144.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate144.errors = vErrors;
return errors === 0;
}
validate144.evaluated = {"props":{"sources":true},"dynamicProps":false,"dynamicItems":false};


function validate54(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate54.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((((((((data.revision === undefined) && (missing0 = "revision")) || ((data.agent === undefined) && (missing0 = "agent"))) || ((data.llm === undefined) && (missing0 = "llm"))) || ((data.memory === undefined) && (missing0 = "memory"))) || ((data.preferences === undefined) && (missing0 = "preferences"))) || ((data.network === undefined) && (missing0 = "network"))) || ((data.diagnostics === undefined) && (missing0 = "diagnostics"))) || ((data.personality === undefined) && (missing0 = "personality"))) || ((data.personalitySettings === undefined) && (missing0 = "personalitySettings"))) || ((data.skills === undefined) && (missing0 = "skills"))) || ((data.timeline === undefined) && (missing0 = "timeline"))){
validate54.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.agent !== undefined){
const _errs1 = errors;
if(!(validate55(data.agent, {instancePath:instancePath+"/agent",parentData:data,parentDataProperty:"agent",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate55.errors : vErrors.concat(validate55.errors);
errors = vErrors.length;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.diagnostics !== undefined){
const _errs2 = errors;
if(!(validate57(data.diagnostics, {instancePath:instancePath+"/diagnostics",parentData:data,parentDataProperty:"diagnostics",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate57.errors : vErrors.concat(validate57.errors);
errors = vErrors.length;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.llm !== undefined){
const _errs3 = errors;
if(!(validate59(data.llm, {instancePath:instancePath+"/llm",parentData:data,parentDataProperty:"llm",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate59.errors : vErrors.concat(validate59.errors);
errors = vErrors.length;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.memory !== undefined){
const _errs4 = errors;
if(!(validate90(data.memory, {instancePath:instancePath+"/memory",parentData:data,parentDataProperty:"memory",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate90.errors : vErrors.concat(validate90.errors);
errors = vErrors.length;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.network !== undefined){
const _errs5 = errors;
if(!(validate116(data.network, {instancePath:instancePath+"/network",parentData:data,parentDataProperty:"network",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate116.errors : vErrors.concat(validate116.errors);
errors = vErrors.length;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.personality !== undefined){
const _errs6 = errors;
if(!(validate118(data.personality, {instancePath:instancePath+"/personality",parentData:data,parentDataProperty:"personality",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate118.errors : vErrors.concat(validate118.errors);
errors = vErrors.length;
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.personalitySettings !== undefined){
const _errs7 = errors;
if(!(validate136(data.personalitySettings, {instancePath:instancePath+"/personalitySettings",parentData:data,parentDataProperty:"personalitySettings",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate136.errors : vErrors.concat(validate136.errors);
errors = vErrors.length;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.preferences !== undefined){
const _errs8 = errors;
if(!(validate138(data.preferences, {instancePath:instancePath+"/preferences",parentData:data,parentDataProperty:"preferences",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate138.errors : vErrors.concat(validate138.errors);
errors = vErrors.length;
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.revision !== undefined){
let data8 = data.revision;
const _errs9 = errors;
const _errs10 = errors;
let valid1 = false;
const _errs11 = errors;
if(typeof data8 !== "string"){
const err0 = {instancePath:instancePath+"/revision",schemaPath:"#/properties/revision/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs11 === errors;
valid1 = valid1 || _valid0;
const _errs13 = errors;
if(data8 !== null){
const err1 = {instancePath:instancePath+"/revision",schemaPath:"#/properties/revision/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs13 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/revision",schemaPath:"#/properties/revision/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate54.errors = vErrors;
return false;
}
else {
errors = _errs10;
if(vErrors !== null){
if(_errs10){
vErrors.length = _errs10;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.skills !== undefined){
let data9 = data.skills;
const _errs15 = errors;
if(errors === _errs15){
if(Array.isArray(data9)){
var valid2 = true;
const len0 = data9.length;
for(let i0=0; i0<len0; i0++){
const _errs17 = errors;
if(typeof data9[i0] !== "string"){
validate54.errors = [{instancePath:instancePath+"/skills/" + i0,schemaPath:"#/properties/skills/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid2 = _errs17 === errors;
if(!valid2){
break;
}
}
}
else {
validate54.errors = [{instancePath:instancePath+"/skills",schemaPath:"#/properties/skills/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs15 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.timeline !== undefined){
const _errs19 = errors;
if(!(validate144(data.timeline, {instancePath:instancePath+"/timeline",parentData:data,parentDataProperty:"timeline",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate144.errors : vErrors.concat(validate144.errors);
errors = vErrors.length;
}
var valid0 = _errs19 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
}
}
}
}
else {
validate54.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate54.errors = vErrors;
return errors === 0;
}
validate54.evaluated = {"props":{"agent":true,"diagnostics":true,"llm":true,"memory":true,"network":true,"personality":true,"personalitySettings":true,"preferences":true,"revision":true,"skills":true,"timeline":true},"dynamicProps":false,"dynamicItems":false};


function validate53(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate53.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((data.success === undefined) && (missing0 = "success")) || ((data.message === undefined) && (missing0 = "message"))) || ((data.data === undefined) && (missing0 = "data"))){
validate53.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.data !== undefined){
let data0 = data.data;
const _errs1 = errors;
const _errs2 = errors;
let valid1 = false;
const _errs3 = errors;
if(!(validate54(data0, {instancePath:instancePath+"/data",parentData:data,parentDataProperty:"data",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate54.errors : vErrors.concat(validate54.errors);
errors = vErrors.length;
}
var _valid0 = _errs3 === errors;
valid1 = valid1 || _valid0;
if(_valid0){
var props0 = {};
props0.agent = true;
props0.diagnostics = true;
props0.llm = true;
props0.memory = true;
props0.network = true;
props0.personality = true;
props0.personalitySettings = true;
props0.preferences = true;
props0.revision = true;
props0.skills = true;
props0.timeline = true;
}
const _errs4 = errors;
if(data0 !== null){
const err0 = {instancePath:instancePath+"/data",schemaPath:"#/properties/data/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs4 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err1 = {instancePath:instancePath+"/data",schemaPath:"#/properties/data/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
validate53.errors = vErrors;
return false;
}
else {
errors = _errs2;
if(vErrors !== null){
if(_errs2){
vErrors.length = _errs2;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.message !== undefined){
const _errs6 = errors;
if(typeof data.message !== "string"){
validate53.errors = [{instancePath:instancePath+"/message",schemaPath:"#/properties/message/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.success !== undefined){
const _errs8 = errors;
if(typeof data.success !== "boolean"){
validate53.errors = [{instancePath:instancePath+"/success",schemaPath:"#/properties/success/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
else {
validate53.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate53.errors = vErrors;
return errors === 0;
}
validate53.evaluated = {"props":{"data":true,"message":true,"success":true},"dynamicProps":false,"dynamicItems":false};

export const validateOnboardingStatusResponse = validate157;
const schema69 = {"properties":{"data":{"$ref":"#/components/schemas/OnboardingStatusDataModel"},"message":{"title":"Message","type":"string"},"success":{"title":"Success","type":"boolean"}},"required":["success","message","data"],"title":"OnboardingStatusResponse","type":"object"};
const schema70 = {"properties":{"completed":{"title":"Completed","type":"boolean"}},"required":["completed"],"title":"OnboardingStatusDataModel","type":"object"};

function validate158(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate158.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((data.completed === undefined) && (missing0 = "completed")){
validate158.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.completed !== undefined){
if(typeof data.completed !== "boolean"){
validate158.errors = [{instancePath:instancePath+"/completed",schemaPath:"#/properties/completed/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
}
}
}
else {
validate158.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate158.errors = vErrors;
return errors === 0;
}
validate158.evaluated = {"props":{"completed":true},"dynamicProps":false,"dynamicItems":false};


function validate157(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate157.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((data.success === undefined) && (missing0 = "success")) || ((data.message === undefined) && (missing0 = "message"))) || ((data.data === undefined) && (missing0 = "data"))){
validate157.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.data !== undefined){
const _errs1 = errors;
if(!(validate158(data.data, {instancePath:instancePath+"/data",parentData:data,parentDataProperty:"data",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate158.errors : vErrors.concat(validate158.errors);
errors = vErrors.length;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.message !== undefined){
const _errs2 = errors;
if(typeof data.message !== "string"){
validate157.errors = [{instancePath:instancePath+"/message",schemaPath:"#/properties/message/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.success !== undefined){
const _errs4 = errors;
if(typeof data.success !== "boolean"){
validate157.errors = [{instancePath:instancePath+"/success",schemaPath:"#/properties/success/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
else {
validate157.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate157.errors = vErrors;
return errors === 0;
}
validate157.evaluated = {"props":{"data":true,"message":true,"success":true},"dynamicProps":false,"dynamicItems":false};

export const validateOnboardingTemplateResponse = validate160;
const schema71 = {"properties":{"data":{"anyOf":[{"$ref":"#/components/schemas/OnboardingTemplateDataModel"},{"type":"null"}],"default":null},"message":{"title":"Message","type":"string"},"success":{"title":"Success","type":"boolean"}},"required":["success","message","data"],"title":"OnboardingTemplateResponse","type":"object"};
const schema72 = {"properties":{"config":{"$ref":"#/components/schemas/SystemConfigModel"}},"required":["config"],"title":"OnboardingTemplateDataModel","type":"object"};

function validate161(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate161.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((data.config === undefined) && (missing0 = "config")){
validate161.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.config !== undefined){
if(!(validate54(data.config, {instancePath:instancePath+"/config",parentData:data,parentDataProperty:"config",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate54.errors : vErrors.concat(validate54.errors);
errors = vErrors.length;
}
}
}
}
else {
validate161.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate161.errors = vErrors;
return errors === 0;
}
validate161.evaluated = {"props":{"config":true},"dynamicProps":false,"dynamicItems":false};


function validate160(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate160.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((data.success === undefined) && (missing0 = "success")) || ((data.message === undefined) && (missing0 = "message"))) || ((data.data === undefined) && (missing0 = "data"))){
validate160.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.data !== undefined){
let data0 = data.data;
const _errs1 = errors;
const _errs2 = errors;
let valid1 = false;
const _errs3 = errors;
if(!(validate161(data0, {instancePath:instancePath+"/data",parentData:data,parentDataProperty:"data",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate161.errors : vErrors.concat(validate161.errors);
errors = vErrors.length;
}
var _valid0 = _errs3 === errors;
valid1 = valid1 || _valid0;
if(_valid0){
var props0 = {};
props0.config = true;
}
const _errs4 = errors;
if(data0 !== null){
const err0 = {instancePath:instancePath+"/data",schemaPath:"#/properties/data/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs4 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err1 = {instancePath:instancePath+"/data",schemaPath:"#/properties/data/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
validate160.errors = vErrors;
return false;
}
else {
errors = _errs2;
if(vErrors !== null){
if(_errs2){
vErrors.length = _errs2;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.message !== undefined){
const _errs6 = errors;
if(typeof data.message !== "string"){
validate160.errors = [{instancePath:instancePath+"/message",schemaPath:"#/properties/message/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.success !== undefined){
const _errs8 = errors;
if(typeof data.success !== "boolean"){
validate160.errors = [{instancePath:instancePath+"/success",schemaPath:"#/properties/success/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
else {
validate160.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate160.errors = vErrors;
return errors === 0;
}
validate160.evaluated = {"props":{"data":true,"message":true,"success":true},"dynamicProps":false,"dynamicItems":false};

export const validateToolConfigResponse = validate164;
const schema73 = {"description":"Tool configuration response","properties":{"category":{"description":"Tool category","title":"Category","type":"string"},"config_specs":{"description":"Config specifications","items":{"$ref":"#/components/schemas/ToolConfigSpecResponse"},"title":"Config Specs","type":"array"},"current_values":{"additionalProperties":true,"description":"Current config values (non-sensitive)","title":"Current Values","type":"object"},"description":{"description":"Tool description","title":"Description","type":"string"},"display_name":{"description":"Human-readable tool name","title":"Display Name","type":"string"},"enabled":{"default":true,"description":"Whether tool is enabled","title":"Enabled","type":"boolean"},"is_multi_provider":{"default":false,"description":"Whether this is a multi-provider tool","title":"Is Multi Provider","type":"boolean"},"is_ready":{"default":true,"description":"Whether tool is configured and ready","title":"Is Ready","type":"boolean"},"name":{"description":"Tool name","title":"Name","type":"string"},"providers":{"description":"Available providers","items":{"$ref":"#/components/schemas/ToolProviderInfo"},"title":"Providers","type":"array"},"revision":{"description":"Opaque settings snapshot revision","pattern":"^[a-f0-9]{64}$","title":"Revision","type":"string"},"version":{"default":"1.0.0","description":"Tool version","title":"Version","type":"string"}},"required":["name","revision","display_name","description","category","version","enabled","is_ready","is_multi_provider","providers","config_specs","current_values"],"title":"ToolConfigResponse","type":"object"};
const schema74 = {"description":"Tool config spec for API response","properties":{"default":{"anyOf":[{},{"type":"null"}],"default":null,"description":"Default value","title":"Default"},"description":{"default":"","description":"Config item description","title":"Description","type":"string"},"enum":{"anyOf":[{"items":{},"type":"array"},{"type":"null"}],"default":null,"description":"Enum values for selection","title":"Enum"},"is_template":{"default":false,"description":"Whether this is a template path (e.g., providers.{provider}.api_key)","title":"Is Template","type":"boolean"},"path":{"description":"Config path (relative to tool namespace)","title":"Path","type":"string"},"placeholder":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"description":"Input placeholder hint","title":"Placeholder"},"providers":{"anyOf":[{"items":{"type":"string"},"type":"array"},{"type":"null"}],"default":null,"description":"Providers that this spec applies to","title":"Providers"},"read_only":{"default":false,"description":"Cannot be changed","title":"Read Only","type":"boolean"},"required":{"default":false,"description":"Whether this config is required","title":"Required","type":"boolean"},"sensitive":{"default":false,"description":"Can be set but not read","title":"Sensitive","type":"boolean"},"type":{"default":"string","description":"Config value type","enum":["string","integer","float","boolean","array","object"],"title":"Type","type":"string"}},"required":["path","type","description","sensitive","read_only","required","default","enum","placeholder","is_template","providers"],"title":"ToolConfigSpecResponse","type":"object"};

function validate165(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate165.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((((((((data.path === undefined) && (missing0 = "path")) || ((data.type === undefined) && (missing0 = "type"))) || ((data.description === undefined) && (missing0 = "description"))) || ((data.sensitive === undefined) && (missing0 = "sensitive"))) || ((data.read_only === undefined) && (missing0 = "read_only"))) || ((data.required === undefined) && (missing0 = "required"))) || ((data.default === undefined) && (missing0 = "default"))) || ((data.enum === undefined) && (missing0 = "enum"))) || ((data.placeholder === undefined) && (missing0 = "placeholder"))) || ((data.is_template === undefined) && (missing0 = "is_template"))) || ((data.providers === undefined) && (missing0 = "providers"))){
validate165.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.default !== undefined){
const _errs1 = errors;
const _errs2 = errors;
let valid1 = false;
var _valid0 = true;
valid1 = valid1 || _valid0;
const _errs3 = errors;
if(data.default !== null){
const err0 = {instancePath:instancePath+"/default",schemaPath:"#/properties/default/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs3 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err1 = {instancePath:instancePath+"/default",schemaPath:"#/properties/default/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
validate165.errors = vErrors;
return false;
}
else {
errors = _errs2;
if(vErrors !== null){
if(_errs2){
vErrors.length = _errs2;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description !== undefined){
const _errs5 = errors;
if(typeof data.description !== "string"){
validate165.errors = [{instancePath:instancePath+"/description",schemaPath:"#/properties/description/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.enum !== undefined){
let data2 = data.enum;
const _errs7 = errors;
const _errs8 = errors;
let valid2 = false;
const _errs9 = errors;
if(errors === _errs9){
if(!(Array.isArray(data2))){
const err2 = {instancePath:instancePath+"/enum",schemaPath:"#/properties/enum/anyOf/0/type",keyword:"type",params:{type: "array"},message:"must be array"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
}
}
var _valid1 = _errs9 === errors;
valid2 = valid2 || _valid1;
const _errs11 = errors;
if(data2 !== null){
const err3 = {instancePath:instancePath+"/enum",schemaPath:"#/properties/enum/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs11 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err4 = {instancePath:instancePath+"/enum",schemaPath:"#/properties/enum/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
validate165.errors = vErrors;
return false;
}
else {
errors = _errs8;
if(vErrors !== null){
if(_errs8){
vErrors.length = _errs8;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.is_template !== undefined){
const _errs13 = errors;
if(typeof data.is_template !== "boolean"){
validate165.errors = [{instancePath:instancePath+"/is_template",schemaPath:"#/properties/is_template/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.path !== undefined){
const _errs15 = errors;
if(typeof data.path !== "string"){
validate165.errors = [{instancePath:instancePath+"/path",schemaPath:"#/properties/path/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs15 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.placeholder !== undefined){
let data5 = data.placeholder;
const _errs17 = errors;
const _errs18 = errors;
let valid3 = false;
const _errs19 = errors;
if(typeof data5 !== "string"){
const err5 = {instancePath:instancePath+"/placeholder",schemaPath:"#/properties/placeholder/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
}
var _valid2 = _errs19 === errors;
valid3 = valid3 || _valid2;
const _errs21 = errors;
if(data5 !== null){
const err6 = {instancePath:instancePath+"/placeholder",schemaPath:"#/properties/placeholder/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid2 = _errs21 === errors;
valid3 = valid3 || _valid2;
if(!valid3){
const err7 = {instancePath:instancePath+"/placeholder",schemaPath:"#/properties/placeholder/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
validate165.errors = vErrors;
return false;
}
else {
errors = _errs18;
if(vErrors !== null){
if(_errs18){
vErrors.length = _errs18;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs17 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.providers !== undefined){
let data6 = data.providers;
const _errs23 = errors;
const _errs24 = errors;
let valid4 = false;
const _errs25 = errors;
if(errors === _errs25){
if(Array.isArray(data6)){
var valid5 = true;
const len0 = data6.length;
for(let i0=0; i0<len0; i0++){
const _errs27 = errors;
if(typeof data6[i0] !== "string"){
const err8 = {instancePath:instancePath+"/providers/" + i0,schemaPath:"#/properties/providers/anyOf/0/items/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
}
var valid5 = _errs27 === errors;
if(!valid5){
break;
}
}
}
else {
const err9 = {instancePath:instancePath+"/providers",schemaPath:"#/properties/providers/anyOf/0/type",keyword:"type",params:{type: "array"},message:"must be array"};
if(vErrors === null){
vErrors = [err9];
}
else {
vErrors.push(err9);
}
errors++;
}
}
var _valid3 = _errs25 === errors;
valid4 = valid4 || _valid3;
const _errs29 = errors;
if(data6 !== null){
const err10 = {instancePath:instancePath+"/providers",schemaPath:"#/properties/providers/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
}
var _valid3 = _errs29 === errors;
valid4 = valid4 || _valid3;
if(!valid4){
const err11 = {instancePath:instancePath+"/providers",schemaPath:"#/properties/providers/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err11];
}
else {
vErrors.push(err11);
}
errors++;
validate165.errors = vErrors;
return false;
}
else {
errors = _errs24;
if(vErrors !== null){
if(_errs24){
vErrors.length = _errs24;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs23 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.read_only !== undefined){
const _errs31 = errors;
if(typeof data.read_only !== "boolean"){
validate165.errors = [{instancePath:instancePath+"/read_only",schemaPath:"#/properties/read_only/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs31 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.required !== undefined){
const _errs33 = errors;
if(typeof data.required !== "boolean"){
validate165.errors = [{instancePath:instancePath+"/required",schemaPath:"#/properties/required/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs33 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.sensitive !== undefined){
const _errs35 = errors;
if(typeof data.sensitive !== "boolean"){
validate165.errors = [{instancePath:instancePath+"/sensitive",schemaPath:"#/properties/sensitive/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs35 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.type !== undefined){
let data11 = data.type;
const _errs37 = errors;
if(typeof data11 !== "string"){
validate165.errors = [{instancePath:instancePath+"/type",schemaPath:"#/properties/type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((((((data11 === "string") || (data11 === "integer")) || (data11 === "float")) || (data11 === "boolean")) || (data11 === "array")) || (data11 === "object"))){
validate165.errors = [{instancePath:instancePath+"/type",schemaPath:"#/properties/type/enum",keyword:"enum",params:{allowedValues: schema74.properties.type.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs37 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
}
}
}
}
else {
validate165.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate165.errors = vErrors;
return errors === 0;
}
validate165.evaluated = {"props":{"default":true,"description":true,"enum":true,"is_template":true,"path":true,"placeholder":true,"providers":true,"read_only":true,"required":true,"sensitive":true,"type":true},"dynamicProps":false,"dynamicItems":false};

const schema75 = {"description":"Provider information for multi-provider tools","properties":{"display_name":{"description":"Human-readable provider name","title":"Display Name","type":"string"},"is_ready":{"description":"Whether provider is configured and ready","title":"Is Ready","type":"boolean"},"name":{"description":"Provider identifier","title":"Name","type":"string"},"required_config":{"description":"Required config paths","items":{"type":"string"},"title":"Required Config","type":"array"}},"required":["name","display_name","is_ready","required_config"],"title":"ToolProviderInfo","type":"object"};

function validate167(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate167.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((data.name === undefined) && (missing0 = "name")) || ((data.display_name === undefined) && (missing0 = "display_name"))) || ((data.is_ready === undefined) && (missing0 = "is_ready"))) || ((data.required_config === undefined) && (missing0 = "required_config"))){
validate167.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.display_name !== undefined){
const _errs1 = errors;
if(typeof data.display_name !== "string"){
validate167.errors = [{instancePath:instancePath+"/display_name",schemaPath:"#/properties/display_name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.is_ready !== undefined){
const _errs3 = errors;
if(typeof data.is_ready !== "boolean"){
validate167.errors = [{instancePath:instancePath+"/is_ready",schemaPath:"#/properties/is_ready/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.name !== undefined){
const _errs5 = errors;
if(typeof data.name !== "string"){
validate167.errors = [{instancePath:instancePath+"/name",schemaPath:"#/properties/name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.required_config !== undefined){
let data3 = data.required_config;
const _errs7 = errors;
if(errors === _errs7){
if(Array.isArray(data3)){
var valid1 = true;
const len0 = data3.length;
for(let i0=0; i0<len0; i0++){
const _errs9 = errors;
if(typeof data3[i0] !== "string"){
validate167.errors = [{instancePath:instancePath+"/required_config/" + i0,schemaPath:"#/properties/required_config/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid1 = _errs9 === errors;
if(!valid1){
break;
}
}
}
else {
validate167.errors = [{instancePath:instancePath+"/required_config",schemaPath:"#/properties/required_config/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
else {
validate167.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate167.errors = vErrors;
return errors === 0;
}
validate167.evaluated = {"props":{"display_name":true,"is_ready":true,"name":true,"required_config":true},"dynamicProps":false,"dynamicItems":false};

const pattern3 = new RegExp("^[a-f0-9]{64}$", "u");

function validate164(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate164.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((((((((data.name === undefined) && (missing0 = "name")) || ((data.revision === undefined) && (missing0 = "revision"))) || ((data.display_name === undefined) && (missing0 = "display_name"))) || ((data.description === undefined) && (missing0 = "description"))) || ((data.category === undefined) && (missing0 = "category"))) || ((data.version === undefined) && (missing0 = "version"))) || ((data.enabled === undefined) && (missing0 = "enabled"))) || ((data.is_ready === undefined) && (missing0 = "is_ready"))) || ((data.is_multi_provider === undefined) && (missing0 = "is_multi_provider"))) || ((data.providers === undefined) && (missing0 = "providers"))) || ((data.config_specs === undefined) && (missing0 = "config_specs"))) || ((data.current_values === undefined) && (missing0 = "current_values"))){
validate164.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.category !== undefined){
const _errs1 = errors;
if(typeof data.category !== "string"){
validate164.errors = [{instancePath:instancePath+"/category",schemaPath:"#/properties/category/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.config_specs !== undefined){
let data1 = data.config_specs;
const _errs3 = errors;
if(errors === _errs3){
if(Array.isArray(data1)){
var valid1 = true;
const len0 = data1.length;
for(let i0=0; i0<len0; i0++){
const _errs5 = errors;
if(!(validate165(data1[i0], {instancePath:instancePath+"/config_specs/" + i0,parentData:data1,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate165.errors : vErrors.concat(validate165.errors);
errors = vErrors.length;
}
var valid1 = _errs5 === errors;
if(!valid1){
break;
}
}
}
else {
validate164.errors = [{instancePath:instancePath+"/config_specs",schemaPath:"#/properties/config_specs/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.current_values !== undefined){
let data3 = data.current_values;
const _errs6 = errors;
if(errors === _errs6){
if(data3 && typeof data3 == "object" && !Array.isArray(data3)){
}
else {
validate164.errors = [{instancePath:instancePath+"/current_values",schemaPath:"#/properties/current_values/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description !== undefined){
const _errs9 = errors;
if(typeof data.description !== "string"){
validate164.errors = [{instancePath:instancePath+"/description",schemaPath:"#/properties/description/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.display_name !== undefined){
const _errs11 = errors;
if(typeof data.display_name !== "string"){
validate164.errors = [{instancePath:instancePath+"/display_name",schemaPath:"#/properties/display_name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.enabled !== undefined){
const _errs13 = errors;
if(typeof data.enabled !== "boolean"){
validate164.errors = [{instancePath:instancePath+"/enabled",schemaPath:"#/properties/enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.is_multi_provider !== undefined){
const _errs15 = errors;
if(typeof data.is_multi_provider !== "boolean"){
validate164.errors = [{instancePath:instancePath+"/is_multi_provider",schemaPath:"#/properties/is_multi_provider/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs15 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.is_ready !== undefined){
const _errs17 = errors;
if(typeof data.is_ready !== "boolean"){
validate164.errors = [{instancePath:instancePath+"/is_ready",schemaPath:"#/properties/is_ready/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs17 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.name !== undefined){
const _errs19 = errors;
if(typeof data.name !== "string"){
validate164.errors = [{instancePath:instancePath+"/name",schemaPath:"#/properties/name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs19 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.providers !== undefined){
let data10 = data.providers;
const _errs21 = errors;
if(errors === _errs21){
if(Array.isArray(data10)){
var valid2 = true;
const len1 = data10.length;
for(let i1=0; i1<len1; i1++){
const _errs23 = errors;
if(!(validate167(data10[i1], {instancePath:instancePath+"/providers/" + i1,parentData:data10,parentDataProperty:i1,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate167.errors : vErrors.concat(validate167.errors);
errors = vErrors.length;
}
var valid2 = _errs23 === errors;
if(!valid2){
break;
}
}
}
else {
validate164.errors = [{instancePath:instancePath+"/providers",schemaPath:"#/properties/providers/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs21 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.revision !== undefined){
let data12 = data.revision;
const _errs24 = errors;
if(errors === _errs24){
if(typeof data12 === "string"){
if(!pattern3.test(data12)){
validate164.errors = [{instancePath:instancePath+"/revision",schemaPath:"#/properties/revision/pattern",keyword:"pattern",params:{pattern: "^[a-f0-9]{64}$"},message:"must match pattern \""+"^[a-f0-9]{64}$"+"\""}];
return false;
}
}
else {
validate164.errors = [{instancePath:instancePath+"/revision",schemaPath:"#/properties/revision/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs24 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.version !== undefined){
const _errs26 = errors;
if(typeof data.version !== "string"){
validate164.errors = [{instancePath:instancePath+"/version",schemaPath:"#/properties/version/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs26 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
}
}
}
}
}
else {
validate164.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate164.errors = vErrors;
return errors === 0;
}
validate164.evaluated = {"props":{"category":true,"config_specs":true,"current_values":true,"description":true,"display_name":true,"enabled":true,"is_multi_provider":true,"is_ready":true,"name":true,"providers":true,"revision":true,"version":true},"dynamicProps":false,"dynamicItems":false};

export const validateToolsListResponse = validate169;
const schema76 = {"description":"Tools list response with config info","properties":{"tools":{"description":"List of tools with config info","items":{"$ref":"#/components/schemas/ToolConfigResponse"},"title":"Tools","type":"array"},"total":{"description":"Total number of tools","title":"Total","type":"integer"}},"required":["tools","total"],"title":"ToolsListResponse","type":"object"};

function validate169(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate169.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((data.tools === undefined) && (missing0 = "tools")) || ((data.total === undefined) && (missing0 = "total"))){
validate169.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.tools !== undefined){
let data0 = data.tools;
const _errs1 = errors;
if(errors === _errs1){
if(Array.isArray(data0)){
var valid1 = true;
const len0 = data0.length;
for(let i0=0; i0<len0; i0++){
const _errs3 = errors;
if(!(validate164(data0[i0], {instancePath:instancePath+"/tools/" + i0,parentData:data0,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate164.errors : vErrors.concat(validate164.errors);
errors = vErrors.length;
}
var valid1 = _errs3 === errors;
if(!valid1){
break;
}
}
}
else {
validate169.errors = [{instancePath:instancePath+"/tools",schemaPath:"#/properties/tools/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.total !== undefined){
let data2 = data.total;
const _errs4 = errors;
if(!((typeof data2 == "number") && (!(data2 % 1) && !isNaN(data2)))){
validate169.errors = [{instancePath:instancePath+"/total",schemaPath:"#/properties/total/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
}
}
}
else {
validate169.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate169.errors = vErrors;
return errors === 0;
}
validate169.evaluated = {"props":{"tools":true,"total":true},"dynamicProps":false,"dynamicItems":false};

export const validateCodeAgentSettingsResponse = validate171;
const schema77 = {"properties":{"settings":{"$ref":"#/components/schemas/CodeAgentSettings"},"workspace_used":{"anyOf":[{"type":"string"},{"type":"null"}],"title":"Workspace Used"}},"required":["settings","workspace_used"],"title":"CodeAgentSettingsResponse","type":"object"};
const schema78 = {"additionalProperties":false,"properties":{"auto_apply":{"default":false,"title":"Auto Apply","type":"boolean"},"claude_code":{"$ref":"#/components/schemas/ClaudeCodeSettings"},"codex":{"$ref":"#/components/schemas/CodexSettings"},"constraints":{"$ref":"#/components/schemas/ConstraintsSettings"},"default_adapter":{"default":"auto","enum":["auto","claude_code","codex"],"title":"Default Adapter","type":"string"},"enabled":{"default":true,"title":"Enabled","type":"boolean"}},"required":["enabled","default_adapter","claude_code","codex","constraints","auto_apply"],"title":"CodeAgentSettings","type":"object"};
const schema79 = {"additionalProperties":false,"properties":{"allowed_tools":{"default":"Read Edit Write Grep Glob Bash(git diff*) Bash(git status*) Bash(pytest*)","title":"Allowed Tools","type":"string"},"binary_path":{"default":"","title":"Binary Path","type":"string"},"default_model":{"default":"","title":"Default Model","type":"string"},"disallowed_tools":{"default":"Bash(git push*) Bash(git commit*) Bash(rm*)","title":"Disallowed Tools","type":"string"},"extra_args":{"items":{"type":"string"},"title":"Extra Args","type":"array"},"max_budget_usd":{"default":5,"title":"Max Budget Usd","type":"number"}},"required":["binary_path","default_model","extra_args","max_budget_usd","allowed_tools","disallowed_tools"],"title":"ClaudeCodeSettings","type":"object"};

function validate173(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate173.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((data.binary_path === undefined) && (missing0 = "binary_path")) || ((data.default_model === undefined) && (missing0 = "default_model"))) || ((data.extra_args === undefined) && (missing0 = "extra_args"))) || ((data.max_budget_usd === undefined) && (missing0 = "max_budget_usd"))) || ((data.allowed_tools === undefined) && (missing0 = "allowed_tools"))) || ((data.disallowed_tools === undefined) && (missing0 = "disallowed_tools"))){
validate173.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!((((((key0 === "allowed_tools") || (key0 === "binary_path")) || (key0 === "default_model")) || (key0 === "disallowed_tools")) || (key0 === "extra_args")) || (key0 === "max_budget_usd"))){
validate173.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.allowed_tools !== undefined){
const _errs2 = errors;
if(typeof data.allowed_tools !== "string"){
validate173.errors = [{instancePath:instancePath+"/allowed_tools",schemaPath:"#/properties/allowed_tools/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.binary_path !== undefined){
const _errs4 = errors;
if(typeof data.binary_path !== "string"){
validate173.errors = [{instancePath:instancePath+"/binary_path",schemaPath:"#/properties/binary_path/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.default_model !== undefined){
const _errs6 = errors;
if(typeof data.default_model !== "string"){
validate173.errors = [{instancePath:instancePath+"/default_model",schemaPath:"#/properties/default_model/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.disallowed_tools !== undefined){
const _errs8 = errors;
if(typeof data.disallowed_tools !== "string"){
validate173.errors = [{instancePath:instancePath+"/disallowed_tools",schemaPath:"#/properties/disallowed_tools/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.extra_args !== undefined){
let data4 = data.extra_args;
const _errs10 = errors;
if(errors === _errs10){
if(Array.isArray(data4)){
var valid1 = true;
const len0 = data4.length;
for(let i0=0; i0<len0; i0++){
const _errs12 = errors;
if(typeof data4[i0] !== "string"){
validate173.errors = [{instancePath:instancePath+"/extra_args/" + i0,schemaPath:"#/properties/extra_args/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid1 = _errs12 === errors;
if(!valid1){
break;
}
}
}
else {
validate173.errors = [{instancePath:instancePath+"/extra_args",schemaPath:"#/properties/extra_args/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs10 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.max_budget_usd !== undefined){
const _errs14 = errors;
if(!(typeof data.max_budget_usd == "number")){
validate173.errors = [{instancePath:instancePath+"/max_budget_usd",schemaPath:"#/properties/max_budget_usd/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
var valid0 = _errs14 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
else {
validate173.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate173.errors = vErrors;
return errors === 0;
}
validate173.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

const schema80 = {"additionalProperties":false,"properties":{"ask_for_approval":{"default":"never","title":"Ask For Approval","type":"string"},"binary_path":{"default":"","title":"Binary Path","type":"string"},"default_model":{"default":"","title":"Default Model","type":"string"},"extra_args":{"items":{"type":"string"},"title":"Extra Args","type":"array"},"sandbox":{"default":"workspace-write","title":"Sandbox","type":"string"}},"required":["binary_path","default_model","extra_args","sandbox","ask_for_approval"],"title":"CodexSettings","type":"object"};

function validate175(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate175.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((data.binary_path === undefined) && (missing0 = "binary_path")) || ((data.default_model === undefined) && (missing0 = "default_model"))) || ((data.extra_args === undefined) && (missing0 = "extra_args"))) || ((data.sandbox === undefined) && (missing0 = "sandbox"))) || ((data.ask_for_approval === undefined) && (missing0 = "ask_for_approval"))){
validate175.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((((key0 === "ask_for_approval") || (key0 === "binary_path")) || (key0 === "default_model")) || (key0 === "extra_args")) || (key0 === "sandbox"))){
validate175.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.ask_for_approval !== undefined){
const _errs2 = errors;
if(typeof data.ask_for_approval !== "string"){
validate175.errors = [{instancePath:instancePath+"/ask_for_approval",schemaPath:"#/properties/ask_for_approval/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.binary_path !== undefined){
const _errs4 = errors;
if(typeof data.binary_path !== "string"){
validate175.errors = [{instancePath:instancePath+"/binary_path",schemaPath:"#/properties/binary_path/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.default_model !== undefined){
const _errs6 = errors;
if(typeof data.default_model !== "string"){
validate175.errors = [{instancePath:instancePath+"/default_model",schemaPath:"#/properties/default_model/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.extra_args !== undefined){
let data3 = data.extra_args;
const _errs8 = errors;
if(errors === _errs8){
if(Array.isArray(data3)){
var valid1 = true;
const len0 = data3.length;
for(let i0=0; i0<len0; i0++){
const _errs10 = errors;
if(typeof data3[i0] !== "string"){
validate175.errors = [{instancePath:instancePath+"/extra_args/" + i0,schemaPath:"#/properties/extra_args/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid1 = _errs10 === errors;
if(!valid1){
break;
}
}
}
else {
validate175.errors = [{instancePath:instancePath+"/extra_args",schemaPath:"#/properties/extra_args/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.sandbox !== undefined){
const _errs12 = errors;
if(typeof data.sandbox !== "string"){
validate175.errors = [{instancePath:instancePath+"/sandbox",schemaPath:"#/properties/sandbox/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
else {
validate175.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate175.errors = vErrors;
return errors === 0;
}
validate175.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

const schema81 = {"additionalProperties":false,"properties":{"default_timeout_s":{"default":600,"maximum":3600,"minimum":60,"title":"Default Timeout S","type":"integer"},"forbid_git_commit":{"default":true,"title":"Forbid Git Commit","type":"boolean"},"forbid_git_push":{"default":true,"title":"Forbid Git Push","type":"boolean"},"forbid_paths":{"items":{"type":"string"},"title":"Forbid Paths","type":"array"}},"required":["forbid_paths","forbid_git_commit","forbid_git_push","default_timeout_s"],"title":"ConstraintsSettings","type":"object"};

function validate177(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate177.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((data.forbid_paths === undefined) && (missing0 = "forbid_paths")) || ((data.forbid_git_commit === undefined) && (missing0 = "forbid_git_commit"))) || ((data.forbid_git_push === undefined) && (missing0 = "forbid_git_push"))) || ((data.default_timeout_s === undefined) && (missing0 = "default_timeout_s"))){
validate177.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!((((key0 === "default_timeout_s") || (key0 === "forbid_git_commit")) || (key0 === "forbid_git_push")) || (key0 === "forbid_paths"))){
validate177.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.default_timeout_s !== undefined){
let data0 = data.default_timeout_s;
const _errs2 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate177.errors = [{instancePath:instancePath+"/default_timeout_s",schemaPath:"#/properties/default_timeout_s/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs2){
if(typeof data0 == "number"){
if(data0 > 3600 || isNaN(data0)){
validate177.errors = [{instancePath:instancePath+"/default_timeout_s",schemaPath:"#/properties/default_timeout_s/maximum",keyword:"maximum",params:{comparison: "<=", limit: 3600},message:"must be <= 3600"}];
return false;
}
else {
if(data0 < 60 || isNaN(data0)){
validate177.errors = [{instancePath:instancePath+"/default_timeout_s",schemaPath:"#/properties/default_timeout_s/minimum",keyword:"minimum",params:{comparison: ">=", limit: 60},message:"must be >= 60"}];
return false;
}
}
}
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.forbid_git_commit !== undefined){
const _errs4 = errors;
if(typeof data.forbid_git_commit !== "boolean"){
validate177.errors = [{instancePath:instancePath+"/forbid_git_commit",schemaPath:"#/properties/forbid_git_commit/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.forbid_git_push !== undefined){
const _errs6 = errors;
if(typeof data.forbid_git_push !== "boolean"){
validate177.errors = [{instancePath:instancePath+"/forbid_git_push",schemaPath:"#/properties/forbid_git_push/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.forbid_paths !== undefined){
let data3 = data.forbid_paths;
const _errs8 = errors;
if(errors === _errs8){
if(Array.isArray(data3)){
var valid1 = true;
const len0 = data3.length;
for(let i0=0; i0<len0; i0++){
const _errs10 = errors;
if(typeof data3[i0] !== "string"){
validate177.errors = [{instancePath:instancePath+"/forbid_paths/" + i0,schemaPath:"#/properties/forbid_paths/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid1 = _errs10 === errors;
if(!valid1){
break;
}
}
}
else {
validate177.errors = [{instancePath:instancePath+"/forbid_paths",schemaPath:"#/properties/forbid_paths/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
else {
validate177.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate177.errors = vErrors;
return errors === 0;
}
validate177.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


function validate172(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate172.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((data.enabled === undefined) && (missing0 = "enabled")) || ((data.default_adapter === undefined) && (missing0 = "default_adapter"))) || ((data.claude_code === undefined) && (missing0 = "claude_code"))) || ((data.codex === undefined) && (missing0 = "codex"))) || ((data.constraints === undefined) && (missing0 = "constraints"))) || ((data.auto_apply === undefined) && (missing0 = "auto_apply"))){
validate172.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!((((((key0 === "auto_apply") || (key0 === "claude_code")) || (key0 === "codex")) || (key0 === "constraints")) || (key0 === "default_adapter")) || (key0 === "enabled"))){
validate172.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.auto_apply !== undefined){
const _errs2 = errors;
if(typeof data.auto_apply !== "boolean"){
validate172.errors = [{instancePath:instancePath+"/auto_apply",schemaPath:"#/properties/auto_apply/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.claude_code !== undefined){
const _errs4 = errors;
if(!(validate173(data.claude_code, {instancePath:instancePath+"/claude_code",parentData:data,parentDataProperty:"claude_code",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate173.errors : vErrors.concat(validate173.errors);
errors = vErrors.length;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.codex !== undefined){
const _errs5 = errors;
if(!(validate175(data.codex, {instancePath:instancePath+"/codex",parentData:data,parentDataProperty:"codex",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate175.errors : vErrors.concat(validate175.errors);
errors = vErrors.length;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.constraints !== undefined){
const _errs6 = errors;
if(!(validate177(data.constraints, {instancePath:instancePath+"/constraints",parentData:data,parentDataProperty:"constraints",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate177.errors : vErrors.concat(validate177.errors);
errors = vErrors.length;
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.default_adapter !== undefined){
let data4 = data.default_adapter;
const _errs7 = errors;
if(typeof data4 !== "string"){
validate172.errors = [{instancePath:instancePath+"/default_adapter",schemaPath:"#/properties/default_adapter/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((data4 === "auto") || (data4 === "claude_code")) || (data4 === "codex"))){
validate172.errors = [{instancePath:instancePath+"/default_adapter",schemaPath:"#/properties/default_adapter/enum",keyword:"enum",params:{allowedValues: schema78.properties.default_adapter.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.enabled !== undefined){
const _errs9 = errors;
if(typeof data.enabled !== "boolean"){
validate172.errors = [{instancePath:instancePath+"/enabled",schemaPath:"#/properties/enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
else {
validate172.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate172.errors = vErrors;
return errors === 0;
}
validate172.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


function validate171(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate171.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((data.settings === undefined) && (missing0 = "settings")) || ((data.workspace_used === undefined) && (missing0 = "workspace_used"))){
validate171.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.settings !== undefined){
const _errs1 = errors;
if(!(validate172(data.settings, {instancePath:instancePath+"/settings",parentData:data,parentDataProperty:"settings",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate172.errors : vErrors.concat(validate172.errors);
errors = vErrors.length;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.workspace_used !== undefined){
let data1 = data.workspace_used;
const _errs2 = errors;
const _errs3 = errors;
let valid1 = false;
const _errs4 = errors;
if(typeof data1 !== "string"){
const err0 = {instancePath:instancePath+"/workspace_used",schemaPath:"#/properties/workspace_used/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs4 === errors;
valid1 = valid1 || _valid0;
const _errs6 = errors;
if(data1 !== null){
const err1 = {instancePath:instancePath+"/workspace_used",schemaPath:"#/properties/workspace_used/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs6 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/workspace_used",schemaPath:"#/properties/workspace_used/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate171.errors = vErrors;
return false;
}
else {
errors = _errs3;
if(vErrors !== null){
if(_errs3){
vErrors.length = _errs3;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
}
}
}
else {
validate171.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate171.errors = vErrors;
return errors === 0;
}
validate171.evaluated = {"props":{"settings":true,"workspace_used":true},"dynamicProps":false,"dynamicItems":false};

export const validateCodeAgentProbeResponse = validate180;
const schema82 = {"properties":{"results":{"$ref":"#/components/schemas/CodeAgentProbeResults"}},"required":["results"],"title":"CodeAgentProbeResponse","type":"object"};
const schema83 = {"properties":{"claude_code":{"$ref":"#/components/schemas/ProbeResult"},"codex":{"$ref":"#/components/schemas/ProbeResult"}},"required":["claude_code","codex"],"title":"CodeAgentProbeResults","type":"object"};
const schema84 = {"additionalProperties":false,"properties":{"binary_path":{"anyOf":[{"type":"string"},{"type":"null"}],"title":"Binary Path"},"detected_at":{"minimum":0,"title":"Detected At","type":"integer"},"error":{"anyOf":[{"type":"string"},{"type":"null"}],"title":"Error"},"extras":{"additionalProperties":true,"title":"Extras","type":"object"},"installed":{"title":"Installed","type":"boolean"},"name":{"enum":["claude_code","codex"],"title":"Name","type":"string"},"version":{"anyOf":[{"type":"string"},{"type":"null"}],"title":"Version"}},"required":["name","installed","binary_path","version","detected_at","error","extras"],"title":"ProbeResult","type":"object"};

function validate182(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate182.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((((data.name === undefined) && (missing0 = "name")) || ((data.installed === undefined) && (missing0 = "installed"))) || ((data.binary_path === undefined) && (missing0 = "binary_path"))) || ((data.version === undefined) && (missing0 = "version"))) || ((data.detected_at === undefined) && (missing0 = "detected_at"))) || ((data.error === undefined) && (missing0 = "error"))) || ((data.extras === undefined) && (missing0 = "extras"))){
validate182.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((((((key0 === "binary_path") || (key0 === "detected_at")) || (key0 === "error")) || (key0 === "extras")) || (key0 === "installed")) || (key0 === "name")) || (key0 === "version"))){
validate182.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.binary_path !== undefined){
let data0 = data.binary_path;
const _errs2 = errors;
const _errs3 = errors;
let valid1 = false;
const _errs4 = errors;
if(typeof data0 !== "string"){
const err0 = {instancePath:instancePath+"/binary_path",schemaPath:"#/properties/binary_path/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs4 === errors;
valid1 = valid1 || _valid0;
const _errs6 = errors;
if(data0 !== null){
const err1 = {instancePath:instancePath+"/binary_path",schemaPath:"#/properties/binary_path/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs6 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/binary_path",schemaPath:"#/properties/binary_path/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate182.errors = vErrors;
return false;
}
else {
errors = _errs3;
if(vErrors !== null){
if(_errs3){
vErrors.length = _errs3;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.detected_at !== undefined){
let data1 = data.detected_at;
const _errs8 = errors;
if(!((typeof data1 == "number") && (!(data1 % 1) && !isNaN(data1)))){
validate182.errors = [{instancePath:instancePath+"/detected_at",schemaPath:"#/properties/detected_at/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs8){
if(typeof data1 == "number"){
if(data1 < 0 || isNaN(data1)){
validate182.errors = [{instancePath:instancePath+"/detected_at",schemaPath:"#/properties/detected_at/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.error !== undefined){
let data2 = data.error;
const _errs10 = errors;
const _errs11 = errors;
let valid2 = false;
const _errs12 = errors;
if(typeof data2 !== "string"){
const err3 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs12 === errors;
valid2 = valid2 || _valid1;
const _errs14 = errors;
if(data2 !== null){
const err4 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs14 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err5 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate182.errors = vErrors;
return false;
}
else {
errors = _errs11;
if(vErrors !== null){
if(_errs11){
vErrors.length = _errs11;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs10 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.extras !== undefined){
let data3 = data.extras;
const _errs16 = errors;
if(errors === _errs16){
if(data3 && typeof data3 == "object" && !Array.isArray(data3)){
}
else {
validate182.errors = [{instancePath:instancePath+"/extras",schemaPath:"#/properties/extras/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs16 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.installed !== undefined){
const _errs19 = errors;
if(typeof data.installed !== "boolean"){
validate182.errors = [{instancePath:instancePath+"/installed",schemaPath:"#/properties/installed/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs19 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.name !== undefined){
let data5 = data.name;
const _errs21 = errors;
if(typeof data5 !== "string"){
validate182.errors = [{instancePath:instancePath+"/name",schemaPath:"#/properties/name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((data5 === "claude_code") || (data5 === "codex"))){
validate182.errors = [{instancePath:instancePath+"/name",schemaPath:"#/properties/name/enum",keyword:"enum",params:{allowedValues: schema84.properties.name.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs21 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.version !== undefined){
let data6 = data.version;
const _errs23 = errors;
const _errs24 = errors;
let valid3 = false;
const _errs25 = errors;
if(typeof data6 !== "string"){
const err6 = {instancePath:instancePath+"/version",schemaPath:"#/properties/version/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid2 = _errs25 === errors;
valid3 = valid3 || _valid2;
const _errs27 = errors;
if(data6 !== null){
const err7 = {instancePath:instancePath+"/version",schemaPath:"#/properties/version/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
}
var _valid2 = _errs27 === errors;
valid3 = valid3 || _valid2;
if(!valid3){
const err8 = {instancePath:instancePath+"/version",schemaPath:"#/properties/version/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
validate182.errors = vErrors;
return false;
}
else {
errors = _errs24;
if(vErrors !== null){
if(_errs24){
vErrors.length = _errs24;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs23 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
}
else {
validate182.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate182.errors = vErrors;
return errors === 0;
}
validate182.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


function validate181(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate181.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((data.claude_code === undefined) && (missing0 = "claude_code")) || ((data.codex === undefined) && (missing0 = "codex"))){
validate181.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.claude_code !== undefined){
const _errs1 = errors;
if(!(validate182(data.claude_code, {instancePath:instancePath+"/claude_code",parentData:data,parentDataProperty:"claude_code",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate182.errors : vErrors.concat(validate182.errors);
errors = vErrors.length;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.codex !== undefined){
const _errs2 = errors;
if(!(validate182(data.codex, {instancePath:instancePath+"/codex",parentData:data,parentDataProperty:"codex",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate182.errors : vErrors.concat(validate182.errors);
errors = vErrors.length;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
}
}
}
else {
validate181.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate181.errors = vErrors;
return errors === 0;
}
validate181.evaluated = {"props":{"claude_code":true,"codex":true},"dynamicProps":false,"dynamicItems":false};


function validate180(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate180.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((data.results === undefined) && (missing0 = "results")){
validate180.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.results !== undefined){
if(!(validate181(data.results, {instancePath:instancePath+"/results",parentData:data,parentDataProperty:"results",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate181.errors : vErrors.concat(validate181.errors);
errors = vErrors.length;
}
}
}
}
else {
validate180.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate180.errors = vErrors;
return errors === 0;
}
validate180.evaluated = {"props":{"results":true},"dynamicProps":false,"dynamicItems":false};
