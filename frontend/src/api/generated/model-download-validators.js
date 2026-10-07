// Generated from production response schemas. Run npm run contracts:generate.
"use strict";
export const validateDownloadProgress = validate53;
const schema20 = {"properties":{"downloaded_bytes":{"default":0,"minimum":0,"title":"Downloaded Bytes","type":"integer"},"eta_seconds":{"anyOf":[{"minimum":0,"type":"number"},{"type":"null"}],"default":null,"title":"Eta Seconds"},"files_completed":{"default":0,"minimum":0,"title":"Files Completed","type":"integer"},"phase":{"default":"connecting","enum":["connecting","downloading","retrying","verifying","completed","cancelled","failed"],"title":"Phase","type":"string"},"speed_bps":{"default":0,"minimum":0,"title":"Speed Bps","type":"number"},"total_bytes":{"anyOf":[{"minimum":0,"type":"integer"},{"type":"null"}],"default":null,"title":"Total Bytes"},"total_files":{"default":0,"minimum":0,"title":"Total Files","type":"integer"}},"required":["phase","downloaded_bytes","total_bytes","speed_bps","eta_seconds","files_completed","total_files"],"title":"DownloadProgress","type":"object"};

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
if((((((((data.phase === undefined) && (missing0 = "phase")) || ((data.downloaded_bytes === undefined) && (missing0 = "downloaded_bytes"))) || ((data.total_bytes === undefined) && (missing0 = "total_bytes"))) || ((data.speed_bps === undefined) && (missing0 = "speed_bps"))) || ((data.eta_seconds === undefined) && (missing0 = "eta_seconds"))) || ((data.files_completed === undefined) && (missing0 = "files_completed"))) || ((data.total_files === undefined) && (missing0 = "total_files"))){
validate53.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.downloaded_bytes !== undefined){
let data0 = data.downloaded_bytes;
const _errs1 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate53.errors = [{instancePath:instancePath+"/downloaded_bytes",schemaPath:"#/properties/downloaded_bytes/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs1){
if(typeof data0 == "number"){
if(data0 < 0 || isNaN(data0)){
validate53.errors = [{instancePath:instancePath+"/downloaded_bytes",schemaPath:"#/properties/downloaded_bytes/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
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
if(data.eta_seconds !== undefined){
let data1 = data.eta_seconds;
const _errs3 = errors;
const _errs4 = errors;
let valid1 = false;
const _errs5 = errors;
if(errors === _errs5){
if(typeof data1 == "number"){
if(data1 < 0 || isNaN(data1)){
const err0 = {instancePath:instancePath+"/eta_seconds",schemaPath:"#/properties/eta_seconds/anyOf/0/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"};
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
const err1 = {instancePath:instancePath+"/eta_seconds",schemaPath:"#/properties/eta_seconds/anyOf/0/type",keyword:"type",params:{type: "number"},message:"must be number"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
}
var _valid0 = _errs5 === errors;
valid1 = valid1 || _valid0;
const _errs7 = errors;
if(data1 !== null){
const err2 = {instancePath:instancePath+"/eta_seconds",schemaPath:"#/properties/eta_seconds/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
}
var _valid0 = _errs7 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err3 = {instancePath:instancePath+"/eta_seconds",schemaPath:"#/properties/eta_seconds/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
validate53.errors = vErrors;
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
if(data.files_completed !== undefined){
let data2 = data.files_completed;
const _errs9 = errors;
if(!((typeof data2 == "number") && (!(data2 % 1) && !isNaN(data2)))){
validate53.errors = [{instancePath:instancePath+"/files_completed",schemaPath:"#/properties/files_completed/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs9){
if(typeof data2 == "number"){
if(data2 < 0 || isNaN(data2)){
validate53.errors = [{instancePath:instancePath+"/files_completed",schemaPath:"#/properties/files_completed/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.phase !== undefined){
let data3 = data.phase;
const _errs11 = errors;
if(typeof data3 !== "string"){
validate53.errors = [{instancePath:instancePath+"/phase",schemaPath:"#/properties/phase/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((((((data3 === "connecting") || (data3 === "downloading")) || (data3 === "retrying")) || (data3 === "verifying")) || (data3 === "completed")) || (data3 === "cancelled")) || (data3 === "failed"))){
validate53.errors = [{instancePath:instancePath+"/phase",schemaPath:"#/properties/phase/enum",keyword:"enum",params:{allowedValues: schema20.properties.phase.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.speed_bps !== undefined){
let data4 = data.speed_bps;
const _errs13 = errors;
if(errors === _errs13){
if(typeof data4 == "number"){
if(data4 < 0 || isNaN(data4)){
validate53.errors = [{instancePath:instancePath+"/speed_bps",schemaPath:"#/properties/speed_bps/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
else {
validate53.errors = [{instancePath:instancePath+"/speed_bps",schemaPath:"#/properties/speed_bps/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.total_bytes !== undefined){
let data5 = data.total_bytes;
const _errs15 = errors;
const _errs16 = errors;
let valid2 = false;
const _errs17 = errors;
if(!((typeof data5 == "number") && (!(data5 % 1) && !isNaN(data5)))){
const err4 = {instancePath:instancePath+"/total_bytes",schemaPath:"#/properties/total_bytes/anyOf/0/type",keyword:"type",params:{type: "integer"},message:"must be integer"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
if(errors === _errs17){
if(typeof data5 == "number"){
if(data5 < 0 || isNaN(data5)){
const err5 = {instancePath:instancePath+"/total_bytes",schemaPath:"#/properties/total_bytes/anyOf/0/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"};
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
var _valid1 = _errs17 === errors;
valid2 = valid2 || _valid1;
const _errs19 = errors;
if(data5 !== null){
const err6 = {instancePath:instancePath+"/total_bytes",schemaPath:"#/properties/total_bytes/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid1 = _errs19 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err7 = {instancePath:instancePath+"/total_bytes",schemaPath:"#/properties/total_bytes/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
validate53.errors = vErrors;
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
if(data.total_files !== undefined){
let data6 = data.total_files;
const _errs21 = errors;
if(!((typeof data6 == "number") && (!(data6 % 1) && !isNaN(data6)))){
validate53.errors = [{instancePath:instancePath+"/total_files",schemaPath:"#/properties/total_files/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs21){
if(typeof data6 == "number"){
if(data6 < 0 || isNaN(data6)){
validate53.errors = [{instancePath:instancePath+"/total_files",schemaPath:"#/properties/total_files/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
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
validate53.evaluated = {"props":{"downloaded_bytes":true,"eta_seconds":true,"files_completed":true,"phase":true,"speed_bps":true,"total_bytes":true,"total_files":true},"dynamicProps":false,"dynamicItems":false};

export const validateModelDownloadStatus = validate54;
const schema21 = {"properties":{"download":{"anyOf":[{"$ref":"#/components/schemas/DownloadProgress"},{"type":"null"}],"default":null},"error":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Error"},"model_id":{"title":"Model Id","type":"string"},"status":{"enum":["downloading","completed","failed","cancelled","not_found"],"title":"Status","type":"string"}},"required":["model_id","status","download","error"],"title":"ModelDownloadStatus","type":"object"};

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
if(((((data.model_id === undefined) && (missing0 = "model_id")) || ((data.status === undefined) && (missing0 = "status"))) || ((data.download === undefined) && (missing0 = "download"))) || ((data.error === undefined) && (missing0 = "error"))){
validate54.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.download !== undefined){
let data0 = data.download;
const _errs1 = errors;
const _errs2 = errors;
let valid1 = false;
const _errs3 = errors;
if(!(validate53(data0, {instancePath:instancePath+"/download",parentData:data,parentDataProperty:"download",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate53.errors : vErrors.concat(validate53.errors);
errors = vErrors.length;
}
var _valid0 = _errs3 === errors;
valid1 = valid1 || _valid0;
if(_valid0){
var props0 = {};
props0.downloaded_bytes = true;
props0.eta_seconds = true;
props0.files_completed = true;
props0.phase = true;
props0.speed_bps = true;
props0.total_bytes = true;
props0.total_files = true;
}
const _errs4 = errors;
if(data0 !== null){
const err0 = {instancePath:instancePath+"/download",schemaPath:"#/properties/download/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
const err1 = {instancePath:instancePath+"/download",schemaPath:"#/properties/download/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
validate54.errors = vErrors;
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
if(data.error !== undefined){
let data1 = data.error;
const _errs6 = errors;
const _errs7 = errors;
let valid2 = false;
const _errs8 = errors;
if(typeof data1 !== "string"){
const err2 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
}
var _valid1 = _errs8 === errors;
valid2 = valid2 || _valid1;
const _errs10 = errors;
if(data1 !== null){
const err3 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs10 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err4 = {instancePath:instancePath+"/error",schemaPath:"#/properties/error/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
validate54.errors = vErrors;
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
if(data.model_id !== undefined){
const _errs12 = errors;
if(typeof data.model_id !== "string"){
validate54.errors = [{instancePath:instancePath+"/model_id",schemaPath:"#/properties/model_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.status !== undefined){
let data3 = data.status;
const _errs14 = errors;
if(typeof data3 !== "string"){
validate54.errors = [{instancePath:instancePath+"/status",schemaPath:"#/properties/status/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((((data3 === "downloading") || (data3 === "completed")) || (data3 === "failed")) || (data3 === "cancelled")) || (data3 === "not_found"))){
validate54.errors = [{instancePath:instancePath+"/status",schemaPath:"#/properties/status/enum",keyword:"enum",params:{allowedValues: schema21.properties.status.enum},message:"must be equal to one of the allowed values"}];
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
else {
validate54.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate54.errors = vErrors;
return errors === 0;
}
validate54.evaluated = {"props":{"download":true,"error":true,"model_id":true,"status":true},"dynamicProps":false,"dynamicItems":false};
