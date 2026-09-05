// Generated from production response schemas. Run npm run contracts:generate.
"use strict";
export const validatePluginPackageResponse = validate53;
const schema20 = {"properties":{"contributions":{"items":{"$ref":"#/components/schemas/PluginContributionResponse"},"title":"Contributions","type":"array"},"current_settings":{"additionalProperties":true,"title":"Current Settings","type":"object"},"enabled":{"title":"Enabled","type":"boolean"},"healthy":{"title":"Healthy","type":"boolean"},"last_error":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Last Error"},"loaded":{"title":"Loaded","type":"boolean"},"manifest":{"$ref":"#/components/schemas/PluginManifestResponse"},"trusted":{"title":"Trusted","type":"boolean"}},"required":["manifest","enabled","trusted","loaded","healthy","last_error","contributions","current_settings"],"title":"PluginPackageResponse","type":"object"};
const schema21 = {"properties":{"contribution_id":{"title":"Contribution Id","type":"string"},"contribution_type":{"title":"Contribution Type","type":"string"},"description":{"title":"Description","type":"string"},"display_name":{"title":"Display Name","type":"string"},"fields":{"items":{"$ref":"#/components/schemas/ExtensionFieldResponse"},"title":"Fields","type":"array"},"metadata":{"additionalProperties":true,"title":"Metadata","type":"object"},"plugin_id":{"title":"Plugin Id","type":"string"},"surface":{"enum":["extensions","tools","timeline"],"title":"Surface","type":"string"}},"required":["plugin_id","contribution_id","contribution_type","display_name","description","surface","fields","metadata"],"title":"PluginContributionResponse","type":"object"};
const schema22 = {"description":"Host-rendered plugin field, including translated presentation metadata.","properties":{"default":{"default":null,"title":"Default"},"depends_on_key":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Depends On Key"},"depends_on_values":{"items":{"type":"string"},"title":"Depends On Values","type":"array"},"description":{"default":"","title":"Description","type":"string"},"description_translated":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Description Translated"},"key":{"title":"Key","type":"string"},"label":{"title":"Label","type":"string"},"label_translated":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Label Translated"},"options":{"items":{"$ref":"#/components/schemas/ExtensionFieldOptionResponse"},"title":"Options","type":"array"},"order":{"default":0,"title":"Order","type":"integer"},"path_kind":{"anyOf":[{"enum":["file","directory"],"type":"string"},{"type":"null"}],"default":null,"title":"Path Kind"},"placeholder":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Placeholder"},"required":{"default":false,"title":"Required","type":"boolean"},"section":{"default":"general","title":"Section","type":"string"},"section_note_translated":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Section Note Translated"},"section_translated":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Section Translated"},"surface":{"default":"extensions","enum":["extensions","tools","timeline"],"title":"Surface","type":"string"},"type":{"default":"input","enum":["switch","select","input","number","secret","path","tags"],"title":"Type","type":"string"}},"required":["key","type","path_kind","label","description","default","required","options","section","surface","order","placeholder","depends_on_key","depends_on_values","label_translated","description_translated","section_translated","section_note_translated"],"title":"ExtensionFieldResponse","type":"object"};
const schema23 = {"properties":{"label":{"title":"Label","type":"string"},"label_translated":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Label Translated"},"value":{"title":"Value","type":"string"}},"required":["label","value","label_translated"],"title":"ExtensionFieldOptionResponse","type":"object"};

function validate56(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate56.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((data.label === undefined) && (missing0 = "label")) || ((data.value === undefined) && (missing0 = "value"))) || ((data.label_translated === undefined) && (missing0 = "label_translated"))){
validate56.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.label !== undefined){
const _errs1 = errors;
if(typeof data.label !== "string"){
validate56.errors = [{instancePath:instancePath+"/label",schemaPath:"#/properties/label/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.label_translated !== undefined){
let data1 = data.label_translated;
const _errs3 = errors;
const _errs4 = errors;
let valid1 = false;
const _errs5 = errors;
if(typeof data1 !== "string"){
const err0 = {instancePath:instancePath+"/label_translated",schemaPath:"#/properties/label_translated/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
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
const err1 = {instancePath:instancePath+"/label_translated",schemaPath:"#/properties/label_translated/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
const err2 = {instancePath:instancePath+"/label_translated",schemaPath:"#/properties/label_translated/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate56.errors = vErrors;
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
if(data.value !== undefined){
const _errs9 = errors;
if(typeof data.value !== "string"){
validate56.errors = [{instancePath:instancePath+"/value",schemaPath:"#/properties/value/type",keyword:"type",params:{type: "string"},message:"must be string"}];
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
else {
validate56.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate56.errors = vErrors;
return errors === 0;
}
validate56.evaluated = {"props":{"label":true,"label_translated":true,"value":true},"dynamicProps":false,"dynamicItems":false};


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
if(((((((((((((((((((data.key === undefined) && (missing0 = "key")) || ((data.type === undefined) && (missing0 = "type"))) || ((data.path_kind === undefined) && (missing0 = "path_kind"))) || ((data.label === undefined) && (missing0 = "label"))) || ((data.description === undefined) && (missing0 = "description"))) || ((data.default === undefined) && (missing0 = "default"))) || ((data.required === undefined) && (missing0 = "required"))) || ((data.options === undefined) && (missing0 = "options"))) || ((data.section === undefined) && (missing0 = "section"))) || ((data.surface === undefined) && (missing0 = "surface"))) || ((data.order === undefined) && (missing0 = "order"))) || ((data.placeholder === undefined) && (missing0 = "placeholder"))) || ((data.depends_on_key === undefined) && (missing0 = "depends_on_key"))) || ((data.depends_on_values === undefined) && (missing0 = "depends_on_values"))) || ((data.label_translated === undefined) && (missing0 = "label_translated"))) || ((data.description_translated === undefined) && (missing0 = "description_translated"))) || ((data.section_translated === undefined) && (missing0 = "section_translated"))) || ((data.section_note_translated === undefined) && (missing0 = "section_note_translated"))){
validate55.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.depends_on_key !== undefined){
let data0 = data.depends_on_key;
const _errs1 = errors;
const _errs2 = errors;
let valid1 = false;
const _errs3 = errors;
if(typeof data0 !== "string"){
const err0 = {instancePath:instancePath+"/depends_on_key",schemaPath:"#/properties/depends_on_key/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
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
const err1 = {instancePath:instancePath+"/depends_on_key",schemaPath:"#/properties/depends_on_key/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
const err2 = {instancePath:instancePath+"/depends_on_key",schemaPath:"#/properties/depends_on_key/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
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
if(data.depends_on_values !== undefined){
let data1 = data.depends_on_values;
const _errs7 = errors;
if(errors === _errs7){
if(Array.isArray(data1)){
var valid2 = true;
const len0 = data1.length;
for(let i0=0; i0<len0; i0++){
const _errs9 = errors;
if(typeof data1[i0] !== "string"){
validate55.errors = [{instancePath:instancePath+"/depends_on_values/" + i0,schemaPath:"#/properties/depends_on_values/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid2 = _errs9 === errors;
if(!valid2){
break;
}
}
}
else {
validate55.errors = [{instancePath:instancePath+"/depends_on_values",schemaPath:"#/properties/depends_on_values/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description !== undefined){
const _errs11 = errors;
if(typeof data.description !== "string"){
validate55.errors = [{instancePath:instancePath+"/description",schemaPath:"#/properties/description/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description_translated !== undefined){
let data4 = data.description_translated;
const _errs13 = errors;
const _errs14 = errors;
let valid3 = false;
const _errs15 = errors;
if(typeof data4 !== "string"){
const err3 = {instancePath:instancePath+"/description_translated",schemaPath:"#/properties/description_translated/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs15 === errors;
valid3 = valid3 || _valid1;
const _errs17 = errors;
if(data4 !== null){
const err4 = {instancePath:instancePath+"/description_translated",schemaPath:"#/properties/description_translated/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs17 === errors;
valid3 = valid3 || _valid1;
if(!valid3){
const err5 = {instancePath:instancePath+"/description_translated",schemaPath:"#/properties/description_translated/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate55.errors = vErrors;
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
if(data.key !== undefined){
const _errs19 = errors;
if(typeof data.key !== "string"){
validate55.errors = [{instancePath:instancePath+"/key",schemaPath:"#/properties/key/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs19 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.label !== undefined){
const _errs21 = errors;
if(typeof data.label !== "string"){
validate55.errors = [{instancePath:instancePath+"/label",schemaPath:"#/properties/label/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs21 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.label_translated !== undefined){
let data7 = data.label_translated;
const _errs23 = errors;
const _errs24 = errors;
let valid4 = false;
const _errs25 = errors;
if(typeof data7 !== "string"){
const err6 = {instancePath:instancePath+"/label_translated",schemaPath:"#/properties/label_translated/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid2 = _errs25 === errors;
valid4 = valid4 || _valid2;
const _errs27 = errors;
if(data7 !== null){
const err7 = {instancePath:instancePath+"/label_translated",schemaPath:"#/properties/label_translated/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
}
var _valid2 = _errs27 === errors;
valid4 = valid4 || _valid2;
if(!valid4){
const err8 = {instancePath:instancePath+"/label_translated",schemaPath:"#/properties/label_translated/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
validate55.errors = vErrors;
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
if(data.options !== undefined){
let data8 = data.options;
const _errs29 = errors;
if(errors === _errs29){
if(Array.isArray(data8)){
var valid5 = true;
const len1 = data8.length;
for(let i1=0; i1<len1; i1++){
const _errs31 = errors;
if(!(validate56(data8[i1], {instancePath:instancePath+"/options/" + i1,parentData:data8,parentDataProperty:i1,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate56.errors : vErrors.concat(validate56.errors);
errors = vErrors.length;
}
var valid5 = _errs31 === errors;
if(!valid5){
break;
}
}
}
else {
validate55.errors = [{instancePath:instancePath+"/options",schemaPath:"#/properties/options/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs29 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.order !== undefined){
let data10 = data.order;
const _errs32 = errors;
if(!((typeof data10 == "number") && (!(data10 % 1) && !isNaN(data10)))){
validate55.errors = [{instancePath:instancePath+"/order",schemaPath:"#/properties/order/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs32 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.path_kind !== undefined){
let data11 = data.path_kind;
const _errs34 = errors;
const _errs35 = errors;
let valid6 = false;
const _errs36 = errors;
if(typeof data11 !== "string"){
const err9 = {instancePath:instancePath+"/path_kind",schemaPath:"#/properties/path_kind/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err9];
}
else {
vErrors.push(err9);
}
errors++;
}
if(!((data11 === "file") || (data11 === "directory"))){
const err10 = {instancePath:instancePath+"/path_kind",schemaPath:"#/properties/path_kind/anyOf/0/enum",keyword:"enum",params:{allowedValues: schema22.properties.path_kind.anyOf[0].enum},message:"must be equal to one of the allowed values"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
}
var _valid3 = _errs36 === errors;
valid6 = valid6 || _valid3;
const _errs38 = errors;
if(data11 !== null){
const err11 = {instancePath:instancePath+"/path_kind",schemaPath:"#/properties/path_kind/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err11];
}
else {
vErrors.push(err11);
}
errors++;
}
var _valid3 = _errs38 === errors;
valid6 = valid6 || _valid3;
if(!valid6){
const err12 = {instancePath:instancePath+"/path_kind",schemaPath:"#/properties/path_kind/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err12];
}
else {
vErrors.push(err12);
}
errors++;
validate55.errors = vErrors;
return false;
}
else {
errors = _errs35;
if(vErrors !== null){
if(_errs35){
vErrors.length = _errs35;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs34 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.placeholder !== undefined){
let data12 = data.placeholder;
const _errs40 = errors;
const _errs41 = errors;
let valid7 = false;
const _errs42 = errors;
if(typeof data12 !== "string"){
const err13 = {instancePath:instancePath+"/placeholder",schemaPath:"#/properties/placeholder/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err13];
}
else {
vErrors.push(err13);
}
errors++;
}
var _valid4 = _errs42 === errors;
valid7 = valid7 || _valid4;
const _errs44 = errors;
if(data12 !== null){
const err14 = {instancePath:instancePath+"/placeholder",schemaPath:"#/properties/placeholder/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err14];
}
else {
vErrors.push(err14);
}
errors++;
}
var _valid4 = _errs44 === errors;
valid7 = valid7 || _valid4;
if(!valid7){
const err15 = {instancePath:instancePath+"/placeholder",schemaPath:"#/properties/placeholder/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err15];
}
else {
vErrors.push(err15);
}
errors++;
validate55.errors = vErrors;
return false;
}
else {
errors = _errs41;
if(vErrors !== null){
if(_errs41){
vErrors.length = _errs41;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs40 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.required !== undefined){
const _errs46 = errors;
if(typeof data.required !== "boolean"){
validate55.errors = [{instancePath:instancePath+"/required",schemaPath:"#/properties/required/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs46 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.section !== undefined){
const _errs48 = errors;
if(typeof data.section !== "string"){
validate55.errors = [{instancePath:instancePath+"/section",schemaPath:"#/properties/section/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs48 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.section_note_translated !== undefined){
let data15 = data.section_note_translated;
const _errs50 = errors;
const _errs51 = errors;
let valid8 = false;
const _errs52 = errors;
if(typeof data15 !== "string"){
const err16 = {instancePath:instancePath+"/section_note_translated",schemaPath:"#/properties/section_note_translated/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err16];
}
else {
vErrors.push(err16);
}
errors++;
}
var _valid5 = _errs52 === errors;
valid8 = valid8 || _valid5;
const _errs54 = errors;
if(data15 !== null){
const err17 = {instancePath:instancePath+"/section_note_translated",schemaPath:"#/properties/section_note_translated/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err17];
}
else {
vErrors.push(err17);
}
errors++;
}
var _valid5 = _errs54 === errors;
valid8 = valid8 || _valid5;
if(!valid8){
const err18 = {instancePath:instancePath+"/section_note_translated",schemaPath:"#/properties/section_note_translated/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err18];
}
else {
vErrors.push(err18);
}
errors++;
validate55.errors = vErrors;
return false;
}
else {
errors = _errs51;
if(vErrors !== null){
if(_errs51){
vErrors.length = _errs51;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs50 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.section_translated !== undefined){
let data16 = data.section_translated;
const _errs56 = errors;
const _errs57 = errors;
let valid9 = false;
const _errs58 = errors;
if(typeof data16 !== "string"){
const err19 = {instancePath:instancePath+"/section_translated",schemaPath:"#/properties/section_translated/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err19];
}
else {
vErrors.push(err19);
}
errors++;
}
var _valid6 = _errs58 === errors;
valid9 = valid9 || _valid6;
const _errs60 = errors;
if(data16 !== null){
const err20 = {instancePath:instancePath+"/section_translated",schemaPath:"#/properties/section_translated/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err20];
}
else {
vErrors.push(err20);
}
errors++;
}
var _valid6 = _errs60 === errors;
valid9 = valid9 || _valid6;
if(!valid9){
const err21 = {instancePath:instancePath+"/section_translated",schemaPath:"#/properties/section_translated/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err21];
}
else {
vErrors.push(err21);
}
errors++;
validate55.errors = vErrors;
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
if(data.surface !== undefined){
let data17 = data.surface;
const _errs62 = errors;
if(typeof data17 !== "string"){
validate55.errors = [{instancePath:instancePath+"/surface",schemaPath:"#/properties/surface/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((data17 === "extensions") || (data17 === "tools")) || (data17 === "timeline"))){
validate55.errors = [{instancePath:instancePath+"/surface",schemaPath:"#/properties/surface/enum",keyword:"enum",params:{allowedValues: schema22.properties.surface.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs62 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.type !== undefined){
let data18 = data.type;
const _errs64 = errors;
if(typeof data18 !== "string"){
validate55.errors = [{instancePath:instancePath+"/type",schemaPath:"#/properties/type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((((((data18 === "switch") || (data18 === "select")) || (data18 === "input")) || (data18 === "number")) || (data18 === "secret")) || (data18 === "path")) || (data18 === "tags"))){
validate55.errors = [{instancePath:instancePath+"/type",schemaPath:"#/properties/type/enum",keyword:"enum",params:{allowedValues: schema22.properties.type.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs64 === errors;
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
validate55.evaluated = {"props":{"default":true,"depends_on_key":true,"depends_on_values":true,"description":true,"description_translated":true,"key":true,"label":true,"label_translated":true,"options":true,"order":true,"path_kind":true,"placeholder":true,"required":true,"section":true,"section_note_translated":true,"section_translated":true,"surface":true,"type":true},"dynamicProps":false,"dynamicItems":false};


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
if(((((((((data.plugin_id === undefined) && (missing0 = "plugin_id")) || ((data.contribution_id === undefined) && (missing0 = "contribution_id"))) || ((data.contribution_type === undefined) && (missing0 = "contribution_type"))) || ((data.display_name === undefined) && (missing0 = "display_name"))) || ((data.description === undefined) && (missing0 = "description"))) || ((data.surface === undefined) && (missing0 = "surface"))) || ((data.fields === undefined) && (missing0 = "fields"))) || ((data.metadata === undefined) && (missing0 = "metadata"))){
validate54.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.contribution_id !== undefined){
const _errs1 = errors;
if(typeof data.contribution_id !== "string"){
validate54.errors = [{instancePath:instancePath+"/contribution_id",schemaPath:"#/properties/contribution_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.contribution_type !== undefined){
const _errs3 = errors;
if(typeof data.contribution_type !== "string"){
validate54.errors = [{instancePath:instancePath+"/contribution_type",schemaPath:"#/properties/contribution_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description !== undefined){
const _errs5 = errors;
if(typeof data.description !== "string"){
validate54.errors = [{instancePath:instancePath+"/description",schemaPath:"#/properties/description/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.display_name !== undefined){
const _errs7 = errors;
if(typeof data.display_name !== "string"){
validate54.errors = [{instancePath:instancePath+"/display_name",schemaPath:"#/properties/display_name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.fields !== undefined){
let data4 = data.fields;
const _errs9 = errors;
if(errors === _errs9){
if(Array.isArray(data4)){
var valid1 = true;
const len0 = data4.length;
for(let i0=0; i0<len0; i0++){
const _errs11 = errors;
if(!(validate55(data4[i0], {instancePath:instancePath+"/fields/" + i0,parentData:data4,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate55.errors : vErrors.concat(validate55.errors);
errors = vErrors.length;
}
var valid1 = _errs11 === errors;
if(!valid1){
break;
}
}
}
else {
validate54.errors = [{instancePath:instancePath+"/fields",schemaPath:"#/properties/fields/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.metadata !== undefined){
let data6 = data.metadata;
const _errs12 = errors;
if(errors === _errs12){
if(data6 && typeof data6 == "object" && !Array.isArray(data6)){
}
else {
validate54.errors = [{instancePath:instancePath+"/metadata",schemaPath:"#/properties/metadata/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.plugin_id !== undefined){
const _errs15 = errors;
if(typeof data.plugin_id !== "string"){
validate54.errors = [{instancePath:instancePath+"/plugin_id",schemaPath:"#/properties/plugin_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs15 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.surface !== undefined){
let data8 = data.surface;
const _errs17 = errors;
if(typeof data8 !== "string"){
validate54.errors = [{instancePath:instancePath+"/surface",schemaPath:"#/properties/surface/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((data8 === "extensions") || (data8 === "tools")) || (data8 === "timeline"))){
validate54.errors = [{instancePath:instancePath+"/surface",schemaPath:"#/properties/surface/enum",keyword:"enum",params:{allowedValues: schema21.properties.surface.enum},message:"must be equal to one of the allowed values"}];
return false;
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
validate54.evaluated = {"props":{"contribution_id":true,"contribution_type":true,"description":true,"display_name":true,"fields":true,"metadata":true,"plugin_id":true,"surface":true},"dynamicProps":false,"dynamicItems":false};

const schema24 = {"properties":{"author":{"title":"Author","type":"string"},"capabilities":{"items":{"$ref":"#/components/schemas/PluginCapability"},"title":"Capabilities","type":"array"},"consented_capabilities":{"anyOf":[{"items":{"$ref":"#/components/schemas/PluginCapability"},"type":"array"},{"type":"null"}],"default":null,"title":"Consented Capabilities"},"contribution_types":{"items":{"type":"string"},"title":"Contribution Types","type":"array"},"description":{"title":"Description","type":"string"},"display_group":{"anyOf":[{"$ref":"#/components/schemas/PluginDisplayGroupSpec"},{"type":"null"}],"default":null},"icon":{"default":"","title":"Icon","type":"string"},"manifest_path":{"title":"Manifest Path","type":"string"},"name":{"title":"Name","type":"string"},"official":{"title":"Official","type":"boolean"},"plugin_dir":{"title":"Plugin Dir","type":"string"},"plugin_id":{"title":"Plugin Id","type":"string"},"source":{"title":"Source","type":"string"},"version":{"title":"Version","type":"string"}},"required":["plugin_id","name","version","description","author","icon","display_group","official","contribution_types","source","plugin_dir","manifest_path","capabilities","consented_capabilities"],"title":"PluginManifestResponse","type":"object"};
const schema25 = {"description":"A single self-declared capability shown to the user for install-time\nconsent. NOT enforced at runtime (no sandbox this iteration).\n\n``capability`` is a permissive ``str`` for forward-compat: a newer\nregistry may declare a capability an older app doesn't know, and that must\nnot break parsing. The authoritative known set is enforced at build time in\nmagi-plugins ``scripts/build-registry.py`` and rendered with a known map +\ngraceful fallback in the frontend. Known values: screen_recording,\naccessibility, calendar, photos, contacts, system_media, filesystem_read,\nfilesystem_write, network, subprocess.","properties":{"capability":{"title":"Capability","type":"string"},"optional":{"default":false,"title":"Optional","type":"boolean"},"reason":{"default":"","title":"Reason","type":"string"},"reason_i18n":{"additionalProperties":{"type":"string"},"title":"Reason I18N","type":"object"},"scope":{"items":{"type":"string"},"title":"Scope","type":"array"}},"required":["capability","scope","optional","reason","reason_i18n"],"title":"PluginCapability","type":"object"};

function validate61(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate61.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((data.capability === undefined) && (missing0 = "capability")) || ((data.scope === undefined) && (missing0 = "scope"))) || ((data.optional === undefined) && (missing0 = "optional"))) || ((data.reason === undefined) && (missing0 = "reason"))) || ((data.reason_i18n === undefined) && (missing0 = "reason_i18n"))){
validate61.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.capability !== undefined){
const _errs1 = errors;
if(typeof data.capability !== "string"){
validate61.errors = [{instancePath:instancePath+"/capability",schemaPath:"#/properties/capability/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.optional !== undefined){
const _errs3 = errors;
if(typeof data.optional !== "boolean"){
validate61.errors = [{instancePath:instancePath+"/optional",schemaPath:"#/properties/optional/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.reason !== undefined){
const _errs5 = errors;
if(typeof data.reason !== "string"){
validate61.errors = [{instancePath:instancePath+"/reason",schemaPath:"#/properties/reason/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.reason_i18n !== undefined){
let data3 = data.reason_i18n;
const _errs7 = errors;
if(errors === _errs7){
if(data3 && typeof data3 == "object" && !Array.isArray(data3)){
for(const key0 in data3){
const _errs10 = errors;
if(typeof data3[key0] !== "string"){
validate61.errors = [{instancePath:instancePath+"/reason_i18n/" + key0.replace(/~/g, "~0").replace(/\//g, "~1"),schemaPath:"#/properties/reason_i18n/additionalProperties/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid1 = _errs10 === errors;
if(!valid1){
break;
}
}
}
else {
validate61.errors = [{instancePath:instancePath+"/reason_i18n",schemaPath:"#/properties/reason_i18n/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.scope !== undefined){
let data5 = data.scope;
const _errs12 = errors;
if(errors === _errs12){
if(Array.isArray(data5)){
var valid2 = true;
const len0 = data5.length;
for(let i0=0; i0<len0; i0++){
const _errs14 = errors;
if(typeof data5[i0] !== "string"){
validate61.errors = [{instancePath:instancePath+"/scope/" + i0,schemaPath:"#/properties/scope/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid2 = _errs14 === errors;
if(!valid2){
break;
}
}
}
else {
validate61.errors = [{instancePath:instancePath+"/scope",schemaPath:"#/properties/scope/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
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
validate61.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate61.errors = vErrors;
return errors === 0;
}
validate61.evaluated = {"props":{"capability":true,"optional":true,"reason":true,"reason_i18n":true,"scope":true},"dynamicProps":false,"dynamicItems":false};

const schema26 = {"description":"User-facing grouping metadata for marketplace and installed plugin UIs.","properties":{"description":{"default":"","title":"Description","type":"string"},"description_i18n":{"additionalProperties":{"type":"string"},"title":"Description I18N","type":"object"},"icon":{"default":"","title":"Icon","type":"string"},"id":{"title":"Id","type":"string"},"member_label":{"default":"","title":"Member Label","type":"string"},"member_label_i18n":{"additionalProperties":{"type":"string"},"title":"Member Label I18N","type":"object"},"member_order":{"default":100,"title":"Member Order","type":"integer"},"name":{"title":"Name","type":"string"},"name_i18n":{"additionalProperties":{"type":"string"},"title":"Name I18N","type":"object"},"order":{"default":100,"title":"Order","type":"integer"}},"required":["id","name","name_i18n","description","description_i18n","icon","order","member_label","member_label_i18n","member_order"],"title":"PluginDisplayGroupSpec","type":"object"};

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
if(((((((((((data.id === undefined) && (missing0 = "id")) || ((data.name === undefined) && (missing0 = "name"))) || ((data.name_i18n === undefined) && (missing0 = "name_i18n"))) || ((data.description === undefined) && (missing0 = "description"))) || ((data.description_i18n === undefined) && (missing0 = "description_i18n"))) || ((data.icon === undefined) && (missing0 = "icon"))) || ((data.order === undefined) && (missing0 = "order"))) || ((data.member_label === undefined) && (missing0 = "member_label"))) || ((data.member_label_i18n === undefined) && (missing0 = "member_label_i18n"))) || ((data.member_order === undefined) && (missing0 = "member_order"))){
validate64.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.description !== undefined){
const _errs1 = errors;
if(typeof data.description !== "string"){
validate64.errors = [{instancePath:instancePath+"/description",schemaPath:"#/properties/description/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description_i18n !== undefined){
let data1 = data.description_i18n;
const _errs3 = errors;
if(errors === _errs3){
if(data1 && typeof data1 == "object" && !Array.isArray(data1)){
for(const key0 in data1){
const _errs6 = errors;
if(typeof data1[key0] !== "string"){
validate64.errors = [{instancePath:instancePath+"/description_i18n/" + key0.replace(/~/g, "~0").replace(/\//g, "~1"),schemaPath:"#/properties/description_i18n/additionalProperties/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid1 = _errs6 === errors;
if(!valid1){
break;
}
}
}
else {
validate64.errors = [{instancePath:instancePath+"/description_i18n",schemaPath:"#/properties/description_i18n/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.icon !== undefined){
const _errs8 = errors;
if(typeof data.icon !== "string"){
validate64.errors = [{instancePath:instancePath+"/icon",schemaPath:"#/properties/icon/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.id !== undefined){
const _errs10 = errors;
if(typeof data.id !== "string"){
validate64.errors = [{instancePath:instancePath+"/id",schemaPath:"#/properties/id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs10 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.member_label !== undefined){
const _errs12 = errors;
if(typeof data.member_label !== "string"){
validate64.errors = [{instancePath:instancePath+"/member_label",schemaPath:"#/properties/member_label/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.member_label_i18n !== undefined){
let data6 = data.member_label_i18n;
const _errs14 = errors;
if(errors === _errs14){
if(data6 && typeof data6 == "object" && !Array.isArray(data6)){
for(const key1 in data6){
const _errs17 = errors;
if(typeof data6[key1] !== "string"){
validate64.errors = [{instancePath:instancePath+"/member_label_i18n/" + key1.replace(/~/g, "~0").replace(/\//g, "~1"),schemaPath:"#/properties/member_label_i18n/additionalProperties/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid2 = _errs17 === errors;
if(!valid2){
break;
}
}
}
else {
validate64.errors = [{instancePath:instancePath+"/member_label_i18n",schemaPath:"#/properties/member_label_i18n/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs14 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.member_order !== undefined){
let data8 = data.member_order;
const _errs19 = errors;
if(!((typeof data8 == "number") && (!(data8 % 1) && !isNaN(data8)))){
validate64.errors = [{instancePath:instancePath+"/member_order",schemaPath:"#/properties/member_order/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs19 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.name !== undefined){
const _errs21 = errors;
if(typeof data.name !== "string"){
validate64.errors = [{instancePath:instancePath+"/name",schemaPath:"#/properties/name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs21 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.name_i18n !== undefined){
let data10 = data.name_i18n;
const _errs23 = errors;
if(errors === _errs23){
if(data10 && typeof data10 == "object" && !Array.isArray(data10)){
for(const key2 in data10){
const _errs26 = errors;
if(typeof data10[key2] !== "string"){
validate64.errors = [{instancePath:instancePath+"/name_i18n/" + key2.replace(/~/g, "~0").replace(/\//g, "~1"),schemaPath:"#/properties/name_i18n/additionalProperties/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid3 = _errs26 === errors;
if(!valid3){
break;
}
}
}
else {
validate64.errors = [{instancePath:instancePath+"/name_i18n",schemaPath:"#/properties/name_i18n/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs23 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.order !== undefined){
let data12 = data.order;
const _errs28 = errors;
if(!((typeof data12 == "number") && (!(data12 % 1) && !isNaN(data12)))){
validate64.errors = [{instancePath:instancePath+"/order",schemaPath:"#/properties/order/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs28 === errors;
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
else {
validate64.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate64.errors = vErrors;
return errors === 0;
}
validate64.evaluated = {"props":{"description":true,"description_i18n":true,"icon":true,"id":true,"member_label":true,"member_label_i18n":true,"member_order":true,"name":true,"name_i18n":true,"order":true},"dynamicProps":false,"dynamicItems":false};


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
if(((((((((((((((data.plugin_id === undefined) && (missing0 = "plugin_id")) || ((data.name === undefined) && (missing0 = "name"))) || ((data.version === undefined) && (missing0 = "version"))) || ((data.description === undefined) && (missing0 = "description"))) || ((data.author === undefined) && (missing0 = "author"))) || ((data.icon === undefined) && (missing0 = "icon"))) || ((data.display_group === undefined) && (missing0 = "display_group"))) || ((data.official === undefined) && (missing0 = "official"))) || ((data.contribution_types === undefined) && (missing0 = "contribution_types"))) || ((data.source === undefined) && (missing0 = "source"))) || ((data.plugin_dir === undefined) && (missing0 = "plugin_dir"))) || ((data.manifest_path === undefined) && (missing0 = "manifest_path"))) || ((data.capabilities === undefined) && (missing0 = "capabilities"))) || ((data.consented_capabilities === undefined) && (missing0 = "consented_capabilities"))){
validate60.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.author !== undefined){
const _errs1 = errors;
if(typeof data.author !== "string"){
validate60.errors = [{instancePath:instancePath+"/author",schemaPath:"#/properties/author/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.capabilities !== undefined){
let data1 = data.capabilities;
const _errs3 = errors;
if(errors === _errs3){
if(Array.isArray(data1)){
var valid1 = true;
const len0 = data1.length;
for(let i0=0; i0<len0; i0++){
const _errs5 = errors;
if(!(validate61(data1[i0], {instancePath:instancePath+"/capabilities/" + i0,parentData:data1,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate61.errors : vErrors.concat(validate61.errors);
errors = vErrors.length;
}
var valid1 = _errs5 === errors;
if(!valid1){
break;
}
}
}
else {
validate60.errors = [{instancePath:instancePath+"/capabilities",schemaPath:"#/properties/capabilities/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.consented_capabilities !== undefined){
let data3 = data.consented_capabilities;
const _errs6 = errors;
const _errs7 = errors;
let valid2 = false;
const _errs8 = errors;
if(errors === _errs8){
if(Array.isArray(data3)){
var valid3 = true;
const len1 = data3.length;
for(let i1=0; i1<len1; i1++){
const _errs10 = errors;
if(!(validate61(data3[i1], {instancePath:instancePath+"/consented_capabilities/" + i1,parentData:data3,parentDataProperty:i1,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate61.errors : vErrors.concat(validate61.errors);
errors = vErrors.length;
}
var valid3 = _errs10 === errors;
if(!valid3){
break;
}
}
}
else {
const err0 = {instancePath:instancePath+"/consented_capabilities",schemaPath:"#/properties/consented_capabilities/anyOf/0/type",keyword:"type",params:{type: "array"},message:"must be array"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
}
var _valid0 = _errs8 === errors;
valid2 = valid2 || _valid0;
const _errs11 = errors;
if(data3 !== null){
const err1 = {instancePath:instancePath+"/consented_capabilities",schemaPath:"#/properties/consented_capabilities/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs11 === errors;
valid2 = valid2 || _valid0;
if(!valid2){
const err2 = {instancePath:instancePath+"/consented_capabilities",schemaPath:"#/properties/consented_capabilities/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate60.errors = vErrors;
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
if(data.contribution_types !== undefined){
let data5 = data.contribution_types;
const _errs13 = errors;
if(errors === _errs13){
if(Array.isArray(data5)){
var valid4 = true;
const len2 = data5.length;
for(let i2=0; i2<len2; i2++){
const _errs15 = errors;
if(typeof data5[i2] !== "string"){
validate60.errors = [{instancePath:instancePath+"/contribution_types/" + i2,schemaPath:"#/properties/contribution_types/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid4 = _errs15 === errors;
if(!valid4){
break;
}
}
}
else {
validate60.errors = [{instancePath:instancePath+"/contribution_types",schemaPath:"#/properties/contribution_types/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description !== undefined){
const _errs17 = errors;
if(typeof data.description !== "string"){
validate60.errors = [{instancePath:instancePath+"/description",schemaPath:"#/properties/description/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs17 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.display_group !== undefined){
let data8 = data.display_group;
const _errs19 = errors;
const _errs20 = errors;
let valid5 = false;
const _errs21 = errors;
if(!(validate64(data8, {instancePath:instancePath+"/display_group",parentData:data,parentDataProperty:"display_group",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate64.errors : vErrors.concat(validate64.errors);
errors = vErrors.length;
}
var _valid1 = _errs21 === errors;
valid5 = valid5 || _valid1;
if(_valid1){
var props0 = {};
props0.description = true;
props0.description_i18n = true;
props0.icon = true;
props0.id = true;
props0.member_label = true;
props0.member_label_i18n = true;
props0.member_order = true;
props0.name = true;
props0.name_i18n = true;
props0.order = true;
}
const _errs22 = errors;
if(data8 !== null){
const err3 = {instancePath:instancePath+"/display_group",schemaPath:"#/properties/display_group/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs22 === errors;
valid5 = valid5 || _valid1;
if(!valid5){
const err4 = {instancePath:instancePath+"/display_group",schemaPath:"#/properties/display_group/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
validate60.errors = vErrors;
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
if(data.icon !== undefined){
const _errs24 = errors;
if(typeof data.icon !== "string"){
validate60.errors = [{instancePath:instancePath+"/icon",schemaPath:"#/properties/icon/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs24 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.manifest_path !== undefined){
const _errs26 = errors;
if(typeof data.manifest_path !== "string"){
validate60.errors = [{instancePath:instancePath+"/manifest_path",schemaPath:"#/properties/manifest_path/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs26 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.name !== undefined){
const _errs28 = errors;
if(typeof data.name !== "string"){
validate60.errors = [{instancePath:instancePath+"/name",schemaPath:"#/properties/name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs28 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.official !== undefined){
const _errs30 = errors;
if(typeof data.official !== "boolean"){
validate60.errors = [{instancePath:instancePath+"/official",schemaPath:"#/properties/official/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs30 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.plugin_dir !== undefined){
const _errs32 = errors;
if(typeof data.plugin_dir !== "string"){
validate60.errors = [{instancePath:instancePath+"/plugin_dir",schemaPath:"#/properties/plugin_dir/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs32 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.plugin_id !== undefined){
const _errs34 = errors;
if(typeof data.plugin_id !== "string"){
validate60.errors = [{instancePath:instancePath+"/plugin_id",schemaPath:"#/properties/plugin_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs34 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.source !== undefined){
const _errs36 = errors;
if(typeof data.source !== "string"){
validate60.errors = [{instancePath:instancePath+"/source",schemaPath:"#/properties/source/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs36 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.version !== undefined){
const _errs38 = errors;
if(typeof data.version !== "string"){
validate60.errors = [{instancePath:instancePath+"/version",schemaPath:"#/properties/version/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs38 === errors;
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
validate60.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate60.errors = vErrors;
return errors === 0;
}
validate60.evaluated = {"props":{"author":true,"capabilities":true,"consented_capabilities":true,"contribution_types":true,"description":true,"display_group":true,"icon":true,"manifest_path":true,"name":true,"official":true,"plugin_dir":true,"plugin_id":true,"source":true,"version":true},"dynamicProps":false,"dynamicItems":false};


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
if(((((((((data.manifest === undefined) && (missing0 = "manifest")) || ((data.enabled === undefined) && (missing0 = "enabled"))) || ((data.trusted === undefined) && (missing0 = "trusted"))) || ((data.loaded === undefined) && (missing0 = "loaded"))) || ((data.healthy === undefined) && (missing0 = "healthy"))) || ((data.last_error === undefined) && (missing0 = "last_error"))) || ((data.contributions === undefined) && (missing0 = "contributions"))) || ((data.current_settings === undefined) && (missing0 = "current_settings"))){
validate53.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.contributions !== undefined){
let data0 = data.contributions;
const _errs1 = errors;
if(errors === _errs1){
if(Array.isArray(data0)){
var valid1 = true;
const len0 = data0.length;
for(let i0=0; i0<len0; i0++){
const _errs3 = errors;
if(!(validate54(data0[i0], {instancePath:instancePath+"/contributions/" + i0,parentData:data0,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate54.errors : vErrors.concat(validate54.errors);
errors = vErrors.length;
}
var valid1 = _errs3 === errors;
if(!valid1){
break;
}
}
}
else {
validate53.errors = [{instancePath:instancePath+"/contributions",schemaPath:"#/properties/contributions/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.current_settings !== undefined){
let data2 = data.current_settings;
const _errs4 = errors;
if(errors === _errs4){
if(data2 && typeof data2 == "object" && !Array.isArray(data2)){
}
else {
validate53.errors = [{instancePath:instancePath+"/current_settings",schemaPath:"#/properties/current_settings/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.enabled !== undefined){
const _errs7 = errors;
if(typeof data.enabled !== "boolean"){
validate53.errors = [{instancePath:instancePath+"/enabled",schemaPath:"#/properties/enabled/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.healthy !== undefined){
const _errs9 = errors;
if(typeof data.healthy !== "boolean"){
validate53.errors = [{instancePath:instancePath+"/healthy",schemaPath:"#/properties/healthy/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.last_error !== undefined){
let data5 = data.last_error;
const _errs11 = errors;
const _errs12 = errors;
let valid2 = false;
const _errs13 = errors;
if(typeof data5 !== "string"){
const err0 = {instancePath:instancePath+"/last_error",schemaPath:"#/properties/last_error/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
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
const err1 = {instancePath:instancePath+"/last_error",schemaPath:"#/properties/last_error/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
const err2 = {instancePath:instancePath+"/last_error",schemaPath:"#/properties/last_error/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate53.errors = vErrors;
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
if(data.loaded !== undefined){
const _errs17 = errors;
if(typeof data.loaded !== "boolean"){
validate53.errors = [{instancePath:instancePath+"/loaded",schemaPath:"#/properties/loaded/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs17 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.manifest !== undefined){
const _errs19 = errors;
if(!(validate60(data.manifest, {instancePath:instancePath+"/manifest",parentData:data,parentDataProperty:"manifest",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate60.errors : vErrors.concat(validate60.errors);
errors = vErrors.length;
}
var valid0 = _errs19 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.trusted !== undefined){
const _errs20 = errors;
if(typeof data.trusted !== "boolean"){
validate53.errors = [{instancePath:instancePath+"/trusted",schemaPath:"#/properties/trusted/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs20 === errors;
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
validate53.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate53.errors = vErrors;
return errors === 0;
}
validate53.evaluated = {"props":{"contributions":true,"current_settings":true,"enabled":true,"healthy":true,"last_error":true,"loaded":true,"manifest":true,"trusted":true},"dynamicProps":false,"dynamicItems":false};

export const validatePluginInstallCandidateResponse = validate67;
const schema27 = {"properties":{"archive_sha256":{"pattern":"^[0-9a-f]{64}$","title":"Archive Sha256","type":"string"},"candidate_id":{"title":"Candidate Id","type":"string"},"expires_at_ms":{"title":"Expires At Ms","type":"integer"},"manifest":{"$ref":"#/components/schemas/PluginManifestResponse"},"package_sha256":{"pattern":"^[0-9a-f]{64}$","title":"Package Sha256","type":"string"}},"required":["candidate_id","archive_sha256","package_sha256","expires_at_ms","manifest"],"title":"PluginInstallCandidateResponse","type":"object"};
const pattern3 = new RegExp("^[0-9a-f]{64}$", "u");

function validate67(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate67.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((data.candidate_id === undefined) && (missing0 = "candidate_id")) || ((data.archive_sha256 === undefined) && (missing0 = "archive_sha256"))) || ((data.package_sha256 === undefined) && (missing0 = "package_sha256"))) || ((data.expires_at_ms === undefined) && (missing0 = "expires_at_ms"))) || ((data.manifest === undefined) && (missing0 = "manifest"))){
validate67.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.archive_sha256 !== undefined){
let data0 = data.archive_sha256;
const _errs1 = errors;
if(errors === _errs1){
if(typeof data0 === "string"){
if(!pattern3.test(data0)){
validate67.errors = [{instancePath:instancePath+"/archive_sha256",schemaPath:"#/properties/archive_sha256/pattern",keyword:"pattern",params:{pattern: "^[0-9a-f]{64}$"},message:"must match pattern \""+"^[0-9a-f]{64}$"+"\""}];
return false;
}
}
else {
validate67.errors = [{instancePath:instancePath+"/archive_sha256",schemaPath:"#/properties/archive_sha256/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.candidate_id !== undefined){
const _errs3 = errors;
if(typeof data.candidate_id !== "string"){
validate67.errors = [{instancePath:instancePath+"/candidate_id",schemaPath:"#/properties/candidate_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.expires_at_ms !== undefined){
let data2 = data.expires_at_ms;
const _errs5 = errors;
if(!((typeof data2 == "number") && (!(data2 % 1) && !isNaN(data2)))){
validate67.errors = [{instancePath:instancePath+"/expires_at_ms",schemaPath:"#/properties/expires_at_ms/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.manifest !== undefined){
const _errs7 = errors;
if(!(validate60(data.manifest, {instancePath:instancePath+"/manifest",parentData:data,parentDataProperty:"manifest",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate60.errors : vErrors.concat(validate60.errors);
errors = vErrors.length;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.package_sha256 !== undefined){
let data4 = data.package_sha256;
const _errs8 = errors;
if(errors === _errs8){
if(typeof data4 === "string"){
if(!pattern3.test(data4)){
validate67.errors = [{instancePath:instancePath+"/package_sha256",schemaPath:"#/properties/package_sha256/pattern",keyword:"pattern",params:{pattern: "^[0-9a-f]{64}$"},message:"must match pattern \""+"^[0-9a-f]{64}$"+"\""}];
return false;
}
}
else {
validate67.errors = [{instancePath:instancePath+"/package_sha256",schemaPath:"#/properties/package_sha256/type",keyword:"type",params:{type: "string"},message:"must be string"}];
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
validate67.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate67.errors = vErrors;
return errors === 0;
}
validate67.evaluated = {"props":{"archive_sha256":true,"candidate_id":true,"expires_at_ms":true,"manifest":true,"package_sha256":true},"dynamicProps":false,"dynamicItems":false};

export const validatePluginInstallJobSnapshot = validate69;
const schema28 = {"properties":{"created_at_ms":{"title":"Created At Ms","type":"integer"},"error":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Error"},"error_code":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Error Code"},"filename":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Filename"},"finished_at_ms":{"anyOf":[{"type":"integer"},{"type":"null"}],"default":null,"title":"Finished At Ms"},"job_id":{"title":"Job Id","type":"string"},"logs":{"items":{"$ref":"#/components/schemas/PluginInstallLogEntry"},"title":"Logs","type":"array"},"message":{"title":"Message","type":"string"},"operation":{"enum":["install","update","upload"],"title":"Operation","type":"string"},"plugin_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Plugin Id"},"progress_pct":{"default":0,"title":"Progress Pct","type":"number"},"result":{"anyOf":[{"$ref":"#/components/schemas/PluginPackageResponse"},{"type":"null"}],"default":null},"stage":{"title":"Stage","type":"string"},"status":{"enum":["queued","running","completed","failed"],"title":"Status","type":"string"},"updated_at_ms":{"title":"Updated At Ms","type":"integer"}},"required":["job_id","operation","plugin_id","filename","status","stage","progress_pct","message","error","error_code","logs","result","created_at_ms","updated_at_ms","finished_at_ms"],"title":"PluginInstallJobSnapshot","type":"object"};
const schema29 = {"properties":{"level":{"default":"info","enum":["info","warning","error"],"title":"Level","type":"string"},"message":{"title":"Message","type":"string"},"stage":{"title":"Stage","type":"string"},"ts_ms":{"title":"Ts Ms","type":"integer"}},"required":["ts_ms","level","stage","message"],"title":"PluginInstallLogEntry","type":"object"};

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
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((data.ts_ms === undefined) && (missing0 = "ts_ms")) || ((data.level === undefined) && (missing0 = "level"))) || ((data.stage === undefined) && (missing0 = "stage"))) || ((data.message === undefined) && (missing0 = "message"))){
validate70.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.level !== undefined){
let data0 = data.level;
const _errs1 = errors;
if(typeof data0 !== "string"){
validate70.errors = [{instancePath:instancePath+"/level",schemaPath:"#/properties/level/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((data0 === "info") || (data0 === "warning")) || (data0 === "error"))){
validate70.errors = [{instancePath:instancePath+"/level",schemaPath:"#/properties/level/enum",keyword:"enum",params:{allowedValues: schema29.properties.level.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.message !== undefined){
const _errs3 = errors;
if(typeof data.message !== "string"){
validate70.errors = [{instancePath:instancePath+"/message",schemaPath:"#/properties/message/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.stage !== undefined){
const _errs5 = errors;
if(typeof data.stage !== "string"){
validate70.errors = [{instancePath:instancePath+"/stage",schemaPath:"#/properties/stage/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.ts_ms !== undefined){
let data3 = data.ts_ms;
const _errs7 = errors;
if(!((typeof data3 == "number") && (!(data3 % 1) && !isNaN(data3)))){
validate70.errors = [{instancePath:instancePath+"/ts_ms",schemaPath:"#/properties/ts_ms/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
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
validate70.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate70.errors = vErrors;
return errors === 0;
}
validate70.evaluated = {"props":{"level":true,"message":true,"stage":true,"ts_ms":true},"dynamicProps":false,"dynamicItems":false};


function validate69(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate69.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((((((((((((data.job_id === undefined) && (missing0 = "job_id")) || ((data.operation === undefined) && (missing0 = "operation"))) || ((data.plugin_id === undefined) && (missing0 = "plugin_id"))) || ((data.filename === undefined) && (missing0 = "filename"))) || ((data.status === undefined) && (missing0 = "status"))) || ((data.stage === undefined) && (missing0 = "stage"))) || ((data.progress_pct === undefined) && (missing0 = "progress_pct"))) || ((data.message === undefined) && (missing0 = "message"))) || ((data.error === undefined) && (missing0 = "error"))) || ((data.error_code === undefined) && (missing0 = "error_code"))) || ((data.logs === undefined) && (missing0 = "logs"))) || ((data.result === undefined) && (missing0 = "result"))) || ((data.created_at_ms === undefined) && (missing0 = "created_at_ms"))) || ((data.updated_at_ms === undefined) && (missing0 = "updated_at_ms"))) || ((data.finished_at_ms === undefined) && (missing0 = "finished_at_ms"))){
validate69.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.created_at_ms !== undefined){
let data0 = data.created_at_ms;
const _errs1 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate69.errors = [{instancePath:instancePath+"/created_at_ms",schemaPath:"#/properties/created_at_ms/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.error !== undefined){
let data1 = data.error;
const _errs3 = errors;
const _errs4 = errors;
let valid1 = false;
const _errs5 = errors;
if(typeof data1 !== "string"){
const err0 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
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
const err1 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
const err2 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate69.errors = vErrors;
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
if(data.error_code !== undefined){
let data2 = data.error_code;
const _errs9 = errors;
const _errs10 = errors;
let valid2 = false;
const _errs11 = errors;
if(typeof data2 !== "string"){
const err3 = {instancePath:instancePath+"/error_code",schemaPath:"#/properties/error_code/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
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
const err4 = {instancePath:instancePath+"/error_code",schemaPath:"#/properties/error_code/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
const err5 = {instancePath:instancePath+"/error_code",schemaPath:"#/properties/error_code/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate69.errors = vErrors;
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
if(data.filename !== undefined){
let data3 = data.filename;
const _errs15 = errors;
const _errs16 = errors;
let valid3 = false;
const _errs17 = errors;
if(typeof data3 !== "string"){
const err6 = {instancePath:instancePath+"/filename",schemaPath:"#/properties/filename/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
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
const err7 = {instancePath:instancePath+"/filename",schemaPath:"#/properties/filename/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
const err8 = {instancePath:instancePath+"/filename",schemaPath:"#/properties/filename/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
validate69.errors = vErrors;
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
if(data.finished_at_ms !== undefined){
let data4 = data.finished_at_ms;
const _errs21 = errors;
const _errs22 = errors;
let valid4 = false;
const _errs23 = errors;
if(!((typeof data4 == "number") && (!(data4 % 1) && !isNaN(data4)))){
const err9 = {instancePath:instancePath+"/finished_at_ms",schemaPath:"#/properties/finished_at_ms/anyOf/0/type",keyword:"type",params:{type: "integer"},message:"must be integer"};
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
const err10 = {instancePath:instancePath+"/finished_at_ms",schemaPath:"#/properties/finished_at_ms/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
const err11 = {instancePath:instancePath+"/finished_at_ms",schemaPath:"#/properties/finished_at_ms/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err11];
}
else {
vErrors.push(err11);
}
errors++;
validate69.errors = vErrors;
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
if(data.job_id !== undefined){
const _errs27 = errors;
if(typeof data.job_id !== "string"){
validate69.errors = [{instancePath:instancePath+"/job_id",schemaPath:"#/properties/job_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs27 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.logs !== undefined){
let data6 = data.logs;
const _errs29 = errors;
if(errors === _errs29){
if(Array.isArray(data6)){
var valid5 = true;
const len0 = data6.length;
for(let i0=0; i0<len0; i0++){
const _errs31 = errors;
if(!(validate70(data6[i0], {instancePath:instancePath+"/logs/" + i0,parentData:data6,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate70.errors : vErrors.concat(validate70.errors);
errors = vErrors.length;
}
var valid5 = _errs31 === errors;
if(!valid5){
break;
}
}
}
else {
validate69.errors = [{instancePath:instancePath+"/logs",schemaPath:"#/properties/logs/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs29 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.message !== undefined){
const _errs32 = errors;
if(typeof data.message !== "string"){
validate69.errors = [{instancePath:instancePath+"/message",schemaPath:"#/properties/message/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs32 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.operation !== undefined){
let data9 = data.operation;
const _errs34 = errors;
if(typeof data9 !== "string"){
validate69.errors = [{instancePath:instancePath+"/operation",schemaPath:"#/properties/operation/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((data9 === "install") || (data9 === "update")) || (data9 === "upload"))){
validate69.errors = [{instancePath:instancePath+"/operation",schemaPath:"#/properties/operation/enum",keyword:"enum",params:{allowedValues: schema28.properties.operation.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs34 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.plugin_id !== undefined){
let data10 = data.plugin_id;
const _errs36 = errors;
const _errs37 = errors;
let valid6 = false;
const _errs38 = errors;
if(typeof data10 !== "string"){
const err12 = {instancePath:instancePath+"/plugin_id",schemaPath:"#/properties/plugin_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err12];
}
else {
vErrors.push(err12);
}
errors++;
}
var _valid4 = _errs38 === errors;
valid6 = valid6 || _valid4;
const _errs40 = errors;
if(data10 !== null){
const err13 = {instancePath:instancePath+"/plugin_id",schemaPath:"#/properties/plugin_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err13];
}
else {
vErrors.push(err13);
}
errors++;
}
var _valid4 = _errs40 === errors;
valid6 = valid6 || _valid4;
if(!valid6){
const err14 = {instancePath:instancePath+"/plugin_id",schemaPath:"#/properties/plugin_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err14];
}
else {
vErrors.push(err14);
}
errors++;
validate69.errors = vErrors;
return false;
}
else {
errors = _errs37;
if(vErrors !== null){
if(_errs37){
vErrors.length = _errs37;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs36 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.progress_pct !== undefined){
const _errs42 = errors;
if(!(typeof data.progress_pct == "number")){
validate69.errors = [{instancePath:instancePath+"/progress_pct",schemaPath:"#/properties/progress_pct/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
var valid0 = _errs42 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.result !== undefined){
let data12 = data.result;
const _errs44 = errors;
const _errs45 = errors;
let valid7 = false;
const _errs46 = errors;
if(!(validate53(data12, {instancePath:instancePath+"/result",parentData:data,parentDataProperty:"result",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate53.errors : vErrors.concat(validate53.errors);
errors = vErrors.length;
}
var _valid5 = _errs46 === errors;
valid7 = valid7 || _valid5;
if(_valid5){
var props0 = {};
props0.contributions = true;
props0.current_settings = true;
props0.enabled = true;
props0.healthy = true;
props0.last_error = true;
props0.loaded = true;
props0.manifest = true;
props0.trusted = true;
}
const _errs47 = errors;
if(data12 !== null){
const err15 = {instancePath:instancePath+"/result",schemaPath:"#/properties/result/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err15];
}
else {
vErrors.push(err15);
}
errors++;
}
var _valid5 = _errs47 === errors;
valid7 = valid7 || _valid5;
if(!valid7){
const err16 = {instancePath:instancePath+"/result",schemaPath:"#/properties/result/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err16];
}
else {
vErrors.push(err16);
}
errors++;
validate69.errors = vErrors;
return false;
}
else {
errors = _errs45;
if(vErrors !== null){
if(_errs45){
vErrors.length = _errs45;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs44 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.stage !== undefined){
const _errs49 = errors;
if(typeof data.stage !== "string"){
validate69.errors = [{instancePath:instancePath+"/stage",schemaPath:"#/properties/stage/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs49 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.status !== undefined){
let data14 = data.status;
const _errs51 = errors;
if(typeof data14 !== "string"){
validate69.errors = [{instancePath:instancePath+"/status",schemaPath:"#/properties/status/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((((data14 === "queued") || (data14 === "running")) || (data14 === "completed")) || (data14 === "failed"))){
validate69.errors = [{instancePath:instancePath+"/status",schemaPath:"#/properties/status/enum",keyword:"enum",params:{allowedValues: schema28.properties.status.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs51 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.updated_at_ms !== undefined){
let data15 = data.updated_at_ms;
const _errs53 = errors;
if(!((typeof data15 == "number") && (!(data15 % 1) && !isNaN(data15)))){
validate69.errors = [{instancePath:instancePath+"/updated_at_ms",schemaPath:"#/properties/updated_at_ms/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs53 === errors;
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
}
else {
validate69.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate69.errors = vErrors;
return errors === 0;
}
validate69.evaluated = {"props":{"created_at_ms":true,"error":true,"error_code":true,"filename":true,"finished_at_ms":true,"job_id":true,"logs":true,"message":true,"operation":true,"plugin_id":true,"progress_pct":true,"result":true,"stage":true,"status":true,"updated_at_ms":true},"dynamicProps":false,"dynamicItems":false};

export const validatePluginRegistryResponse = validate73;
const schema30 = {"properties":{"install_fingerprint":{"pattern":"^[0-9a-f]{64}$","title":"Install Fingerprint","type":"string"},"plugins":{"items":{"$ref":"#/components/schemas/PluginRegistryEntryResponse"},"title":"Plugins","type":"array"},"registry_version":{"const":"4","title":"Registry Version","type":"string"}},"required":["plugins","registry_version","install_fingerprint"],"title":"PluginRegistryResponse","type":"object"};
const schema31 = {"properties":{"author":{"default":"","title":"Author","type":"string"},"capabilities":{"items":{"$ref":"#/components/schemas/PluginCapability"},"title":"Capabilities","type":"array"},"contribution_types":{"items":{"type":"string"},"title":"Contribution Types","type":"array"},"data_locality":{"default":"","title":"Data Locality","type":"string"},"description":{"default":"","title":"Description","type":"string"},"description_i18n":{"additionalProperties":{"type":"string"},"title":"Description I18N","type":"object"},"display_group":{"anyOf":[{"$ref":"#/components/schemas/PluginDisplayGroupSpec"},{"type":"null"}],"default":null},"homepage":{"default":"","title":"Homepage","type":"string"},"icon":{"default":"","title":"Icon","type":"string"},"installed":{"default":false,"title":"Installed","type":"boolean"},"installed_version":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Installed Version"},"min_sdk_version":{"default":"","title":"Min Sdk Version","type":"string"},"name":{"title":"Name","type":"string"},"name_i18n":{"additionalProperties":{"type":"string"},"title":"Name I18N","type":"object"},"official":{"default":false,"title":"Official","type":"boolean"},"path":{"default":"","title":"Path","type":"string"},"platforms":{"items":{"type":"string"},"title":"Platforms","type":"array"},"plugin_id":{"title":"Plugin Id","type":"string"},"repository":{"default":"","title":"Repository","type":"string"},"update_available":{"default":false,"title":"Update Available","type":"boolean"},"version":{"title":"Version","type":"string"}},"required":["plugin_id","name","name_i18n","version","description","description_i18n","author","icon","display_group","official","data_locality","contribution_types","platforms","min_sdk_version","homepage","repository","path","installed","installed_version","update_available","capabilities"],"title":"PluginRegistryEntryResponse","type":"object"};

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
if((((((((((((((((((((((data.plugin_id === undefined) && (missing0 = "plugin_id")) || ((data.name === undefined) && (missing0 = "name"))) || ((data.name_i18n === undefined) && (missing0 = "name_i18n"))) || ((data.version === undefined) && (missing0 = "version"))) || ((data.description === undefined) && (missing0 = "description"))) || ((data.description_i18n === undefined) && (missing0 = "description_i18n"))) || ((data.author === undefined) && (missing0 = "author"))) || ((data.icon === undefined) && (missing0 = "icon"))) || ((data.display_group === undefined) && (missing0 = "display_group"))) || ((data.official === undefined) && (missing0 = "official"))) || ((data.data_locality === undefined) && (missing0 = "data_locality"))) || ((data.contribution_types === undefined) && (missing0 = "contribution_types"))) || ((data.platforms === undefined) && (missing0 = "platforms"))) || ((data.min_sdk_version === undefined) && (missing0 = "min_sdk_version"))) || ((data.homepage === undefined) && (missing0 = "homepage"))) || ((data.repository === undefined) && (missing0 = "repository"))) || ((data.path === undefined) && (missing0 = "path"))) || ((data.installed === undefined) && (missing0 = "installed"))) || ((data.installed_version === undefined) && (missing0 = "installed_version"))) || ((data.update_available === undefined) && (missing0 = "update_available"))) || ((data.capabilities === undefined) && (missing0 = "capabilities"))){
validate74.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.author !== undefined){
const _errs1 = errors;
if(typeof data.author !== "string"){
validate74.errors = [{instancePath:instancePath+"/author",schemaPath:"#/properties/author/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.capabilities !== undefined){
let data1 = data.capabilities;
const _errs3 = errors;
if(errors === _errs3){
if(Array.isArray(data1)){
var valid1 = true;
const len0 = data1.length;
for(let i0=0; i0<len0; i0++){
const _errs5 = errors;
if(!(validate61(data1[i0], {instancePath:instancePath+"/capabilities/" + i0,parentData:data1,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate61.errors : vErrors.concat(validate61.errors);
errors = vErrors.length;
}
var valid1 = _errs5 === errors;
if(!valid1){
break;
}
}
}
else {
validate74.errors = [{instancePath:instancePath+"/capabilities",schemaPath:"#/properties/capabilities/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.contribution_types !== undefined){
let data3 = data.contribution_types;
const _errs6 = errors;
if(errors === _errs6){
if(Array.isArray(data3)){
var valid2 = true;
const len1 = data3.length;
for(let i1=0; i1<len1; i1++){
const _errs8 = errors;
if(typeof data3[i1] !== "string"){
validate74.errors = [{instancePath:instancePath+"/contribution_types/" + i1,schemaPath:"#/properties/contribution_types/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid2 = _errs8 === errors;
if(!valid2){
break;
}
}
}
else {
validate74.errors = [{instancePath:instancePath+"/contribution_types",schemaPath:"#/properties/contribution_types/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.data_locality !== undefined){
const _errs10 = errors;
if(typeof data.data_locality !== "string"){
validate74.errors = [{instancePath:instancePath+"/data_locality",schemaPath:"#/properties/data_locality/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs10 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description !== undefined){
const _errs12 = errors;
if(typeof data.description !== "string"){
validate74.errors = [{instancePath:instancePath+"/description",schemaPath:"#/properties/description/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description_i18n !== undefined){
let data7 = data.description_i18n;
const _errs14 = errors;
if(errors === _errs14){
if(data7 && typeof data7 == "object" && !Array.isArray(data7)){
for(const key0 in data7){
const _errs17 = errors;
if(typeof data7[key0] !== "string"){
validate74.errors = [{instancePath:instancePath+"/description_i18n/" + key0.replace(/~/g, "~0").replace(/\//g, "~1"),schemaPath:"#/properties/description_i18n/additionalProperties/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid3 = _errs17 === errors;
if(!valid3){
break;
}
}
}
else {
validate74.errors = [{instancePath:instancePath+"/description_i18n",schemaPath:"#/properties/description_i18n/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs14 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.display_group !== undefined){
let data9 = data.display_group;
const _errs19 = errors;
const _errs20 = errors;
let valid4 = false;
const _errs21 = errors;
if(!(validate64(data9, {instancePath:instancePath+"/display_group",parentData:data,parentDataProperty:"display_group",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate64.errors : vErrors.concat(validate64.errors);
errors = vErrors.length;
}
var _valid0 = _errs21 === errors;
valid4 = valid4 || _valid0;
if(_valid0){
var props0 = {};
props0.description = true;
props0.description_i18n = true;
props0.icon = true;
props0.id = true;
props0.member_label = true;
props0.member_label_i18n = true;
props0.member_order = true;
props0.name = true;
props0.name_i18n = true;
props0.order = true;
}
const _errs22 = errors;
if(data9 !== null){
const err0 = {instancePath:instancePath+"/display_group",schemaPath:"#/properties/display_group/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs22 === errors;
valid4 = valid4 || _valid0;
if(!valid4){
const err1 = {instancePath:instancePath+"/display_group",schemaPath:"#/properties/display_group/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
validate74.errors = vErrors;
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
if(data.homepage !== undefined){
const _errs24 = errors;
if(typeof data.homepage !== "string"){
validate74.errors = [{instancePath:instancePath+"/homepage",schemaPath:"#/properties/homepage/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs24 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.icon !== undefined){
const _errs26 = errors;
if(typeof data.icon !== "string"){
validate74.errors = [{instancePath:instancePath+"/icon",schemaPath:"#/properties/icon/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs26 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.installed !== undefined){
const _errs28 = errors;
if(typeof data.installed !== "boolean"){
validate74.errors = [{instancePath:instancePath+"/installed",schemaPath:"#/properties/installed/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs28 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.installed_version !== undefined){
let data13 = data.installed_version;
const _errs30 = errors;
const _errs31 = errors;
let valid5 = false;
const _errs32 = errors;
if(typeof data13 !== "string"){
const err2 = {instancePath:instancePath+"/installed_version",schemaPath:"#/properties/installed_version/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
}
var _valid1 = _errs32 === errors;
valid5 = valid5 || _valid1;
const _errs34 = errors;
if(data13 !== null){
const err3 = {instancePath:instancePath+"/installed_version",schemaPath:"#/properties/installed_version/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs34 === errors;
valid5 = valid5 || _valid1;
if(!valid5){
const err4 = {instancePath:instancePath+"/installed_version",schemaPath:"#/properties/installed_version/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
validate74.errors = vErrors;
return false;
}
else {
errors = _errs31;
if(vErrors !== null){
if(_errs31){
vErrors.length = _errs31;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs30 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.min_sdk_version !== undefined){
const _errs36 = errors;
if(typeof data.min_sdk_version !== "string"){
validate74.errors = [{instancePath:instancePath+"/min_sdk_version",schemaPath:"#/properties/min_sdk_version/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs36 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.name !== undefined){
const _errs38 = errors;
if(typeof data.name !== "string"){
validate74.errors = [{instancePath:instancePath+"/name",schemaPath:"#/properties/name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs38 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.name_i18n !== undefined){
let data16 = data.name_i18n;
const _errs40 = errors;
if(errors === _errs40){
if(data16 && typeof data16 == "object" && !Array.isArray(data16)){
for(const key1 in data16){
const _errs43 = errors;
if(typeof data16[key1] !== "string"){
validate74.errors = [{instancePath:instancePath+"/name_i18n/" + key1.replace(/~/g, "~0").replace(/\//g, "~1"),schemaPath:"#/properties/name_i18n/additionalProperties/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid6 = _errs43 === errors;
if(!valid6){
break;
}
}
}
else {
validate74.errors = [{instancePath:instancePath+"/name_i18n",schemaPath:"#/properties/name_i18n/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs40 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.official !== undefined){
const _errs45 = errors;
if(typeof data.official !== "boolean"){
validate74.errors = [{instancePath:instancePath+"/official",schemaPath:"#/properties/official/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs45 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.path !== undefined){
const _errs47 = errors;
if(typeof data.path !== "string"){
validate74.errors = [{instancePath:instancePath+"/path",schemaPath:"#/properties/path/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs47 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.platforms !== undefined){
let data20 = data.platforms;
const _errs49 = errors;
if(errors === _errs49){
if(Array.isArray(data20)){
var valid7 = true;
const len2 = data20.length;
for(let i2=0; i2<len2; i2++){
const _errs51 = errors;
if(typeof data20[i2] !== "string"){
validate74.errors = [{instancePath:instancePath+"/platforms/" + i2,schemaPath:"#/properties/platforms/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid7 = _errs51 === errors;
if(!valid7){
break;
}
}
}
else {
validate74.errors = [{instancePath:instancePath+"/platforms",schemaPath:"#/properties/platforms/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs49 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.plugin_id !== undefined){
const _errs53 = errors;
if(typeof data.plugin_id !== "string"){
validate74.errors = [{instancePath:instancePath+"/plugin_id",schemaPath:"#/properties/plugin_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs53 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.repository !== undefined){
const _errs55 = errors;
if(typeof data.repository !== "string"){
validate74.errors = [{instancePath:instancePath+"/repository",schemaPath:"#/properties/repository/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs55 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.update_available !== undefined){
const _errs57 = errors;
if(typeof data.update_available !== "boolean"){
validate74.errors = [{instancePath:instancePath+"/update_available",schemaPath:"#/properties/update_available/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs57 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.version !== undefined){
const _errs59 = errors;
if(typeof data.version !== "string"){
validate74.errors = [{instancePath:instancePath+"/version",schemaPath:"#/properties/version/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs59 === errors;
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
}
}
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
validate74.evaluated = {"props":{"author":true,"capabilities":true,"contribution_types":true,"data_locality":true,"description":true,"description_i18n":true,"display_group":true,"homepage":true,"icon":true,"installed":true,"installed_version":true,"min_sdk_version":true,"name":true,"name_i18n":true,"official":true,"path":true,"platforms":true,"plugin_id":true,"repository":true,"update_available":true,"version":true},"dynamicProps":false,"dynamicItems":false};


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
if((((data.plugins === undefined) && (missing0 = "plugins")) || ((data.registry_version === undefined) && (missing0 = "registry_version"))) || ((data.install_fingerprint === undefined) && (missing0 = "install_fingerprint"))){
validate73.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.install_fingerprint !== undefined){
let data0 = data.install_fingerprint;
const _errs1 = errors;
if(errors === _errs1){
if(typeof data0 === "string"){
if(!pattern3.test(data0)){
validate73.errors = [{instancePath:instancePath+"/install_fingerprint",schemaPath:"#/properties/install_fingerprint/pattern",keyword:"pattern",params:{pattern: "^[0-9a-f]{64}$"},message:"must match pattern \""+"^[0-9a-f]{64}$"+"\""}];
return false;
}
}
else {
validate73.errors = [{instancePath:instancePath+"/install_fingerprint",schemaPath:"#/properties/install_fingerprint/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.plugins !== undefined){
let data1 = data.plugins;
const _errs3 = errors;
if(errors === _errs3){
if(Array.isArray(data1)){
var valid1 = true;
const len0 = data1.length;
for(let i0=0; i0<len0; i0++){
const _errs5 = errors;
if(!(validate74(data1[i0], {instancePath:instancePath+"/plugins/" + i0,parentData:data1,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate74.errors : vErrors.concat(validate74.errors);
errors = vErrors.length;
}
var valid1 = _errs5 === errors;
if(!valid1){
break;
}
}
}
else {
validate73.errors = [{instancePath:instancePath+"/plugins",schemaPath:"#/properties/plugins/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.registry_version !== undefined){
let data3 = data.registry_version;
const _errs6 = errors;
if(typeof data3 !== "string"){
validate73.errors = [{instancePath:instancePath+"/registry_version",schemaPath:"#/properties/registry_version/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if("4" !== data3){
validate73.errors = [{instancePath:instancePath+"/registry_version",schemaPath:"#/properties/registry_version/const",keyword:"const",params:{allowedValue: "4"},message:"must be equal to constant"}];
return false;
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
else {
validate73.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate73.errors = vErrors;
return errors === 0;
}
validate73.evaluated = {"props":{"install_fingerprint":true,"plugins":true,"registry_version":true},"dynamicProps":false,"dynamicItems":false};

export const validatePluginSettingsActionRunResponse = validate78;
const schema32 = {"properties":{"action_id":{"title":"Action Id","type":"string"},"data":{"additionalProperties":true,"title":"Data","type":"object"},"message":{"default":"","title":"Message","type":"string"},"plugin_id":{"title":"Plugin Id","type":"string"},"session_id":{"title":"Session Id","type":"string"},"settings_updates":{"additionalProperties":true,"title":"Settings Updates","type":"object"},"status":{"enum":["pending","succeeded","failed","cancelled"],"title":"Status","type":"string"}},"required":["plugin_id","action_id","session_id","status","message","data","settings_updates"],"title":"PluginSettingsActionRunResponse","type":"object"};

function validate78(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate78.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((((data.plugin_id === undefined) && (missing0 = "plugin_id")) || ((data.action_id === undefined) && (missing0 = "action_id"))) || ((data.session_id === undefined) && (missing0 = "session_id"))) || ((data.status === undefined) && (missing0 = "status"))) || ((data.message === undefined) && (missing0 = "message"))) || ((data.data === undefined) && (missing0 = "data"))) || ((data.settings_updates === undefined) && (missing0 = "settings_updates"))){
validate78.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.action_id !== undefined){
const _errs1 = errors;
if(typeof data.action_id !== "string"){
validate78.errors = [{instancePath:instancePath+"/action_id",schemaPath:"#/properties/action_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.data !== undefined){
let data1 = data.data;
const _errs3 = errors;
if(errors === _errs3){
if(data1 && typeof data1 == "object" && !Array.isArray(data1)){
}
else {
validate78.errors = [{instancePath:instancePath+"/data",schemaPath:"#/properties/data/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.message !== undefined){
const _errs6 = errors;
if(typeof data.message !== "string"){
validate78.errors = [{instancePath:instancePath+"/message",schemaPath:"#/properties/message/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.plugin_id !== undefined){
const _errs8 = errors;
if(typeof data.plugin_id !== "string"){
validate78.errors = [{instancePath:instancePath+"/plugin_id",schemaPath:"#/properties/plugin_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.session_id !== undefined){
const _errs10 = errors;
if(typeof data.session_id !== "string"){
validate78.errors = [{instancePath:instancePath+"/session_id",schemaPath:"#/properties/session_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs10 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.settings_updates !== undefined){
let data5 = data.settings_updates;
const _errs12 = errors;
if(errors === _errs12){
if(data5 && typeof data5 == "object" && !Array.isArray(data5)){
}
else {
validate78.errors = [{instancePath:instancePath+"/settings_updates",schemaPath:"#/properties/settings_updates/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.status !== undefined){
let data6 = data.status;
const _errs15 = errors;
if(typeof data6 !== "string"){
validate78.errors = [{instancePath:instancePath+"/status",schemaPath:"#/properties/status/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((((data6 === "pending") || (data6 === "succeeded")) || (data6 === "failed")) || (data6 === "cancelled"))){
validate78.errors = [{instancePath:instancePath+"/status",schemaPath:"#/properties/status/enum",keyword:"enum",params:{allowedValues: schema32.properties.status.enum},message:"must be equal to one of the allowed values"}];
return false;
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
validate78.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate78.errors = vErrors;
return errors === 0;
}
validate78.evaluated = {"props":{"action_id":true,"data":true,"message":true,"plugin_id":true,"session_id":true,"settings_updates":true,"status":true},"dynamicProps":false,"dynamicItems":false};

export const validatePluginSettingsResourceResponse = validate79;
const schema33 = {"properties":{"data":{"default":null,"title":"Data"},"plugin_id":{"title":"Plugin Id","type":"string"},"resource_name":{"title":"Resource Name","type":"string"},"resource_type":{"title":"Resource Type","type":"string"}},"required":["plugin_id","resource_name","resource_type","data"],"title":"PluginSettingsResourceResponse","type":"object"};

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
if(((((data.plugin_id === undefined) && (missing0 = "plugin_id")) || ((data.resource_name === undefined) && (missing0 = "resource_name"))) || ((data.resource_type === undefined) && (missing0 = "resource_type"))) || ((data.data === undefined) && (missing0 = "data"))){
validate79.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.plugin_id !== undefined){
const _errs1 = errors;
if(typeof data.plugin_id !== "string"){
validate79.errors = [{instancePath:instancePath+"/plugin_id",schemaPath:"#/properties/plugin_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.resource_name !== undefined){
const _errs3 = errors;
if(typeof data.resource_name !== "string"){
validate79.errors = [{instancePath:instancePath+"/resource_name",schemaPath:"#/properties/resource_name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.resource_type !== undefined){
const _errs5 = errors;
if(typeof data.resource_type !== "string"){
validate79.errors = [{instancePath:instancePath+"/resource_type",schemaPath:"#/properties/resource_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
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
validate79.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate79.errors = vErrors;
return errors === 0;
}
validate79.evaluated = {"props":{"data":true,"plugin_id":true,"resource_name":true,"resource_type":true},"dynamicProps":false,"dynamicItems":false};

export const validatePluginsListResponse = validate80;
const schema34 = {"properties":{"plugins":{"items":{"$ref":"#/components/schemas/PluginPackageResponse"},"title":"Plugins","type":"array"},"total":{"title":"Total","type":"integer"}},"required":["plugins","total"],"title":"PluginsListResponse","type":"object"};

function validate80(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate80.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((data.plugins === undefined) && (missing0 = "plugins")) || ((data.total === undefined) && (missing0 = "total"))){
validate80.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.plugins !== undefined){
let data0 = data.plugins;
const _errs1 = errors;
if(errors === _errs1){
if(Array.isArray(data0)){
var valid1 = true;
const len0 = data0.length;
for(let i0=0; i0<len0; i0++){
const _errs3 = errors;
if(!(validate53(data0[i0], {instancePath:instancePath+"/plugins/" + i0,parentData:data0,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate53.errors : vErrors.concat(validate53.errors);
errors = vErrors.length;
}
var valid1 = _errs3 === errors;
if(!valid1){
break;
}
}
}
else {
validate80.errors = [{instancePath:instancePath+"/plugins",schemaPath:"#/properties/plugins/type",keyword:"type",params:{type: "array"},message:"must be array"}];
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
validate80.errors = [{instancePath:instancePath+"/total",schemaPath:"#/properties/total/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
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
validate80.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate80.errors = vErrors;
return errors === 0;
}
validate80.evaluated = {"props":{"plugins":true,"total":true},"dynamicProps":false,"dynamicItems":false};
