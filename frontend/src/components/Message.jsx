function Message({ message }) {
  if (!message.text) {
    return null;
  }

  return (
    <div className={`message message-${message.type}`} role="status">
      {message.text}
    </div>
  );
}


export default Message;